#!/usr/bin/env python3
"""Run the fixed server-first production update with precise local fallbacks."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shlex
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from audit_market_sources import audit_sources, load_json
from fetch_investing_bond_ohlc import (
    BOND_SPECS as INVESTING_BOND_SPECS,
    fetch_html as fetch_investing_html,
    rows_from_html as rows_from_investing_html,
    write_csv as write_investing_csv,
)
from market_dashboard import (
    DASHBOARD_DATA,
    GERMANY_BOND_SPECS,
    INVESTING_SPECS,
    JAPAN_BOND_SPECS,
    KOREA_BOND_SPECS,
    LOCAL_DATA,
    MOEX_SPECS,
    NIKKEI_SPECS,
    WSCN_SPECS,
    YAHOO_SPECS,
    SeriesSpec,
    fetch_smbs_koribor_rows_by_tenor,
    fetch_moex_index_ohlc,
    fetch_yahoo_ohlc,
    merge_ohlc_rows,
    read_ohlc,
    row_date_key,
    write_ohlc,
)


ROOT = Path(__file__).resolve().parent
POLICY_PATH = ROOT / "source_update_policy.json"
LOCAL_PATCH_REPORT = ROOT / "dashboard" / "local_patch_report.json"
DEFAULT_SERVER = os.environ.get("MARKET_DASHBOARD_SERVER", "root@43.133.168.211")
DEFAULT_SERVER_DIR = os.environ.get("MARKET_DASHBOARD_SERVER_DIR", "/opt/global-market-dashboard")
DEFAULT_SSH_KEY = Path(
    os.environ.get(
        "MARKET_DASHBOARD_SSH_KEY",
        str(Path.home() / "Desktop" / "国债汇率" / "sol.pem"),
    )
)
LOCK_PATH = Path("/tmp/global-market-dashboard-production-update.lock")


def dashboard_spec_map() -> dict[str, SeriesSpec]:
    values: list[SeriesSpec] = [*WSCN_SPECS, *MOEX_SPECS, *YAHOO_SPECS, *NIKKEI_SPECS]
    values.extend(spec for spec, *_ in JAPAN_BOND_SPECS)
    values.extend(spec for spec, *_ in GERMANY_BOND_SPECS)
    values.extend(spec for spec, *_ in KOREA_BOND_SPECS)
    values.extend(spec for spec, _ in INVESTING_SPECS)
    return {spec.key: spec for spec in values}


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    check: bool = False,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print("$", shlex.join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.stdout and not quiet:
        print(result.stdout.rstrip(), flush=True)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {shlex.join(command)}")
    return result


def ssh_base(args: argparse.Namespace) -> list[str]:
    return [
        "ssh",
        "-i",
        str(args.ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        args.server,
    ]


def scp_base(args: argparse.Namespace) -> list[str]:
    return [
        "scp",
        "-i",
        str(args.ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
    ]


def remote_command(args: argparse.Namespace, script: str, *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return run_command([*ssh_base(args), "bash", "-s"], input_text=script, check=check)


def download_json(args: argparse.Namespace, remote_relative_path: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="market-dashboard-") as temp_dir:
        destination = Path(temp_dir) / Path(remote_relative_path).name
        source = f"{args.server}:{args.server_dir.rstrip('/')}/{remote_relative_path}"
        run_command([*scp_base(args), source, str(destination)], check=True, quiet=True)
        return load_json(destination)


def fetch_server_snapshot(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    result = remote_command(args, "systemctl start global-market-dashboard-update.service\n")
    snapshot = download_json(args, "dashboard/latest_market_snapshot.json")
    return result.returncode, snapshot


def patch_yahoo(keys: Iterable[str], start: date, end: date) -> tuple[list[dict[str, Any]], list[str]]:
    specs = {spec.key: spec for spec in YAHOO_SPECS}
    patched: list[dict[str, Any]] = []
    failures: list[str] = []
    for key in sorted(set(keys)):
        spec = specs.get(key)
        if not spec:
            failures.append(f"{key}: not a Yahoo series")
            continue
        try:
            rows = fetch_yahoo_ohlc(spec.symbol, start, end)
        except Exception as exc:
            failures.append(f"{key}: {type(exc).__name__}: {exc}")
            continue
        if not rows:
            failures.append(f"{key}: empty Yahoo response")
            continue
        path = DASHBOARD_DATA / spec.cache_file
        existing = read_ohlc(path) if path.exists() else []
        if existing and rows[-1]["date"] < existing[-1]["date"].isoformat():
            failures.append(f"{key}: incoming Yahoo data is older than local cache")
            continue
        write_ohlc(path, rows)
        patched.append(
            {
                "key": key,
                "latest": str(rows[-1]["date"]),
                "rows": len(rows),
                "files": [str(path.relative_to(ROOT))],
            }
        )
        print(f"PATCH Yahoo {key} {rows[0]['date']} -> {rows[-1]['date']} ({len(rows)} rows)")
    return patched, failures


def patch_smbs_koribor(keys: Iterable[str], start: date, end: date) -> tuple[list[dict[str, Any]], list[str]]:
    requested = sorted(set(keys))
    if not requested:
        return [], []
    specs = {
        spec.key: (spec, source_key)
        for spec, source_kind, source_key in KOREA_BOND_SPECS
        if source_kind == "smbs-koribor"
    }
    unsupported = [key for key in requested if key not in specs]
    failures = [f"{key}: not an SMBS KORIBOR series" for key in unsupported]
    supported = [key for key in requested if key in specs]
    if not supported:
        return [], failures
    existing_by_key: dict[str, list[dict[str, Any]]] = {}
    for key in supported:
        spec, _tenor = specs[key]
        path = DASHBOARD_DATA / spec.cache_file
        existing_by_key[key] = read_ohlc(path) if path.exists() else []
    refresh_start = start
    if existing_by_key and all(existing_by_key.values()):
        refresh_start = max(
            start,
            min(row_date_key(rows[-1]) for rows in existing_by_key.values()) - timedelta(days=7),
        )
    try:
        rows_by_tenor = fetch_smbs_koribor_rows_by_tenor(refresh_start, end)
    except Exception as exc:
        failures.extend(f"{key}: {type(exc).__name__}: {exc}" for key in supported)
        return [], failures

    patched: list[dict[str, Any]] = []
    for key in supported:
        spec, tenor = specs[key]
        incoming = rows_by_tenor.get(tenor, [])
        if not incoming:
            failures.append(f"{key}: empty SMBS KORIBOR response")
            continue
        for row in incoming:
            row["source_symbol"] = spec.symbol
            row["source"] = "SMBS KORIBOR money-market fixing; local public-data patch"
        path = DASHBOARD_DATA / spec.cache_file
        existing = existing_by_key.get(key, [])
        if existing and row_date_key(incoming[-1]) < row_date_key(existing[-1]):
            failures.append(f"{key}: incoming SMBS data is older than local cache")
            continue
        merged = merge_ohlc_rows(existing, incoming)
        write_ohlc(path, merged)
        patched.append(
            {
                "key": key,
                "latest": str(merged[-1]["date"]),
                "rows": len(incoming),
                "files": [str(path.relative_to(ROOT))],
            }
        )
        print(f"PATCH SMBS {key} {incoming[0]['date']} -> {incoming[-1]['date']} ({len(incoming)} rows)")
    return patched, failures


def patch_investing(keys: Iterable[str], policy: dict[str, Any], start: date, end: date) -> tuple[list[dict[str, Any]], list[str]]:
    investing_map = policy.get("investing_symbol_map", {})
    specs = dashboard_spec_map()
    patched: list[dict[str, Any]] = []
    failures: list[str] = []
    for key in sorted(set(keys)):
        investing_key = investing_map.get(key)
        investing_spec = INVESTING_BOND_SPECS.get(investing_key or "")
        dashboard_spec = specs.get(key)
        if not investing_spec or not dashboard_spec:
            failures.append(f"{key}: missing Investing/source policy mapping")
            continue
        try:
            rows = rows_from_investing_html(fetch_investing_html(investing_spec, start, end))
        except Exception as exc:
            failures.append(f"{key}: {type(exc).__name__}: {exc}")
            continue
        if not rows:
            failures.append(f"{key}: empty Investing response")
            continue
        raw_path = LOCAL_DATA / investing_spec.output_name
        write_investing_csv(raw_path, rows)
        cache_path = DASHBOARD_DATA / dashboard_spec.cache_file
        existing = read_ohlc(cache_path) if cache_path.exists() else []
        incoming: list[dict[str, Any]] = []
        for row in rows:
            incoming.append(
                {
                    **row,
                    "source_symbol": investing_spec.source_symbol,
                    "source": "Investing.com historical table via local public-data patch",
                }
            )
        merged = merge_ohlc_rows(existing, incoming)
        write_ohlc(cache_path, merged)
        patched.append(
            {
                "key": key,
                "latest": str(rows[-1]["date"]),
                "rows": len(rows),
                "files": [str(cache_path.relative_to(ROOT)), str(raw_path.relative_to(ROOT))],
            }
        )
        print(f"PATCH Investing {key} {rows[0]['date']} -> {rows[-1]['date']} ({len(rows)} rows)")
    return patched, failures


def patch_moex_indices(keys: Iterable[str], policy: dict[str, Any], start: date, end: date) -> tuple[list[dict[str, Any]], list[str]]:
    overrides = policy.get("local_source_overrides", {})
    specs = dashboard_spec_map()
    patched: list[dict[str, Any]] = []
    failures: list[str] = []
    for key in sorted(set(keys)):
        override = overrides.get(key, {})
        dashboard_spec = specs.get(key)
        if override.get("provider") != "moex_iss" or not override.get("symbol") or not dashboard_spec:
            failures.append(f"{key}: missing MOEX ISS/source policy mapping")
            continue
        symbol = str(override["symbol"])
        try:
            incoming = fetch_moex_index_ohlc(symbol, start, end)
        except Exception as exc:
            failures.append(f"{key}: {type(exc).__name__}: {exc}")
            continue
        if not incoming:
            failures.append(f"{key}: empty MOEX ISS response")
            continue
        cache_path = DASHBOARD_DATA / dashboard_spec.cache_file
        existing = read_ohlc(cache_path) if cache_path.exists() else []
        if existing and row_date_key(incoming[-1]) < row_date_key(existing[-1]):
            failures.append(f"{key}: incoming MOEX ISS data is older than local cache")
            continue
        merged = merge_ohlc_rows(existing, incoming)
        write_ohlc(cache_path, merged)
        patched.append(
            {
                "key": key,
                "latest": str(incoming[-1]["date"]),
                "rows": len(incoming),
                "files": [str(cache_path.relative_to(ROOT))],
            }
        )
        print(f"PATCH MOEX ISS {key} {incoming[0]['date']} -> {incoming[-1]['date']} ({len(incoming)} rows)")
    return patched, failures


def write_patch_report(patched: list[dict[str, Any]], last_fetch_at: str) -> None:
    report = {
        "patched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "after_fetch_at": last_fetch_at,
        "keys": sorted({item["key"] for item in patched}),
        "latest": {item["key"]: item["latest"] for item in patched},
    }
    LOCAL_PATCH_REPORT.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_PATCH_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_public_upload_paths(relative_paths: Iterable[str]) -> list[str]:
    allowed_exact = {"dashboard/local_patch_report.json"}
    allowed_prefixes = ("dashboard/data/", "data/")
    paths = sorted(set(relative_paths))
    for value in paths:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe upload path: {value}")
        if value not in allowed_exact and not value.startswith(allowed_prefixes):
            raise ValueError(f"non-public upload path: {value}")
        if any(part in {".private", ".env"} for part in path.parts):
            raise ValueError(f"private upload path: {value}")
    return paths


def upload_public_patch(args: argparse.Namespace, relative_paths: Iterable[str]) -> None:
    paths = validate_public_upload_paths(relative_paths)
    if not paths:
        return
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        manifest = Path(handle.name)
        handle.write("\n".join(paths) + "\n")
    try:
        command = [
            "rsync",
            "-avz",
            "--no-owner",
            "--no-group",
            f"--files-from={manifest}",
            "-e",
            f"ssh -i {shlex.quote(str(args.ssh_key))} -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
            "./",
            f"{args.server}:{args.server_dir.rstrip('/')}/",
        ]
        run_command(command, cwd=ROOT, check=True)
    finally:
        manifest.unlink(missing_ok=True)


def finalize_server(args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    server_dir = shlex.quote(args.server_dir)
    script = f"""set -euo pipefail
cd {server_dir}
chown -R globaldash:globaldash dashboard data
find dashboard data -type d -exec chmod 755 {{}} +
find dashboard data -type f -exec chmod 644 {{}} +
runuser -u globaldash -- python3 quant_fund_snapshot.py
runuser -u globaldash -- python3 market_dashboard.py --no-fetch
runuser -u globaldash -- python3 validate_market_dashboard.py
runuser -u globaldash -- python3 audit_market_sources.py
"""
    return remote_command(args, script)


def print_final_summary(args: argparse.Namespace) -> None:
    snapshot = download_json(args, "dashboard/latest_market_snapshot.json")
    status = {row.get("key"): row for row in snapshot.get("series_status", [])}
    print("FINAL generated_at", snapshot.get("generated_at"))
    for key in ["US_EQUITY", "DXY", "VIX", "GOLD", "USOIL", "RU_EQUITY"]:
        row = status.get(key, {})
        print("FINAL", key, row.get("latest_date", "MISSING"), row.get("latest", ""))
    if args.redact_quant_summary:
        print("FINAL quant protected")
    else:
        quant = download_json(args, "dashboard/quant_fund_snapshot.json")
        print(
            "FINAL quant",
            quant.get("generated_at", ""),
            quant.get("futures", {}).get("latest_pct"),
            quant.get("options", {}).get("latest_pct"),
        )
    report = audit_sources(snapshot, load_json(POLICY_PATH))
    print("FINAL source_audit", "PASS" if report["ok"] else "FAIL", "warnings", len(report["warnings"]))
    if not report["ok"]:
        for message in report["errors"]:
            print("FINAL ERROR", message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--server-dir", default=DEFAULT_SERVER_DIR)
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_SSH_KEY)
    parser.add_argument("--weekly", action="store_true", help="Also refresh full local OHLC for all weekly Investing fallbacks.")
    parser.add_argument("--audit-only", action="store_true", help="Read and audit the current server snapshot without updating it.")
    parser.add_argument("--skip-required-local", action="store_true", help="Do not refresh the fixed local-required source list.")
    parser.add_argument(
        "--redact-quant-summary",
        action="store_true",
        help="Do not read or print quant percentages in the final command summary.",
    )
    parser.add_argument("--lookback-days", type=int, default=540)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.ssh_key.exists():
        print(f"ERROR missing SSH key: {args.ssh_key}", file=sys.stderr)
        return 2
    policy = load_json(POLICY_PATH)
    with LOCK_PATH.open("w", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"ERROR another production update holds {LOCK_PATH}", file=sys.stderr)
            return 2

        if args.audit_only:
            snapshot = download_json(args, "dashboard/latest_market_snapshot.json")
            report = audit_sources(snapshot, policy)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ok"] else 1

        server_status, snapshot = fetch_server_snapshot(args)
        source_report = audit_sources(snapshot, policy)
        print(json.dumps(source_report, ensure_ascii=False, indent=2))
        if server_status and (source_report["last_fetch_age_hours"] is None or source_report["last_fetch_age_hours"] > 12):
            print("ERROR server update failed before producing a current fetch audit", file=sys.stderr)
            return 1

        yahoo_keys = set(source_report["local_patch_candidates"]) & set(policy.get("yahoo_patch_on_failure", []))
        smbs_keys = set(source_report["local_patch_candidates"]) & set(policy.get("smbs_patch_on_failure", []))
        investing_keys: set[str] = set()
        if not args.skip_required_local:
            investing_keys.update(policy.get("local_required", []))
        if args.weekly:
            investing_keys.update(policy.get("local_weekly_ohlc", []))

        override_keys = investing_keys & set(policy.get("local_source_overrides", {}))
        investing_keys -= override_keys

        end = date.today()
        start = end - timedelta(days=args.lookback_days)
        yahoo_patched, yahoo_failures = patch_yahoo(yahoo_keys, start, end)
        smbs_patched, smbs_failures = patch_smbs_koribor(smbs_keys, start, end)
        investing_patched, investing_failures = patch_investing(investing_keys, policy, start, end)
        override_patched, override_failures = patch_moex_indices(override_keys, policy, start, end)
        patched = [*yahoo_patched, *smbs_patched, *investing_patched, *override_patched]
        failures = [*yahoo_failures, *smbs_failures, *investing_failures, *override_failures]
        for failure in failures:
            print("PATCH ERROR", failure)

        required_failures = set(policy.get("local_required", [])) - {item["key"] for item in patched}
        unresolved_yahoo = yahoo_keys - {item["key"] for item in yahoo_patched}
        unresolved_smbs = smbs_keys - {item["key"] for item in smbs_patched}
        if required_failures or unresolved_yahoo or unresolved_smbs:
            print(
                "ERROR unresolved local patches:",
                " ".join(sorted(required_failures | unresolved_yahoo | unresolved_smbs)),
                file=sys.stderr,
            )
            return 1

        if patched:
            write_patch_report(patched, str(snapshot.get("last_fetch_at") or ""))
            upload_paths = [path for item in patched for path in item["files"]]
            upload_paths.append(str(LOCAL_PATCH_REPORT.relative_to(ROOT)))
            upload_public_patch(args, upload_paths)
            final_result = finalize_server(args)
            if final_result.returncode:
                return final_result.returncode

        print_final_summary(args)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
