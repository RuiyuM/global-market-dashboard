#!/usr/bin/env python3
"""Audit the last dashboard fetch against the fixed production source policy."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_SNAPSHOT = ROOT / "dashboard" / "latest_market_snapshot.json"
DEFAULT_POLICY = ROOT / "source_update_policy.json"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def audit_sources(snapshot: dict[str, Any], policy: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    records = snapshot.get("fetch_records")
    if not isinstance(records, list):
        records = []
    by_key = {str(row.get("key")): row for row in records if isinstance(row, dict) and row.get("key")}
    expected_degraded = {
        key
        for source in policy.get("server_blocked", {}).values()
        for key in source.get("keys", [])
    }
    yahoo_keys = set(policy.get("yahoo_patch_on_failure", []))
    errors: list[str] = []
    warnings: list[str] = []
    local_patch: set[str] = set()
    last_fetch_at = parse_iso(str(snapshot.get("last_fetch_at") or ""))
    patch_report = snapshot.get("local_patch_report")
    if not isinstance(patch_report, dict):
        patch_report = {}
    patched_keys = {str(key) for key in patch_report.get("keys", [])}
    patched_at = parse_iso(str(patch_report.get("patched_at") or ""))
    patch_is_current = bool(patched_at and last_fetch_at and patched_at >= last_fetch_at)

    if not records:
        errors.append("missing fetch_records; run a network fetch before auditing")

    if not last_fetch_at:
        errors.append("missing or invalid last_fetch_at")
        last_fetch_age_hours = None
    else:
        last_fetch_age_hours = max(0.0, (now.astimezone(timezone.utc) - last_fetch_at.astimezone(timezone.utc)).total_seconds() / 3600)
        if last_fetch_age_hours > 72:
            errors.append(f"last network fetch is {last_fetch_age_hours:.1f} hours old")

    for key, row in sorted(by_key.items()):
        status = str(row.get("status") or "")
        error = str(row.get("error") or "")
        if status in {"error", "empty", "pending", ""}:
            if patch_is_current and key in patched_keys:
                warnings.append(f"{key}: server status={status or 'missing'} remediated by local public-data patch")
            else:
                errors.append(f"{key}: status={status or 'missing'} {error}".strip())
            if key in yahoo_keys and (not patch_is_current or key not in patched_keys):
                local_patch.add(key)
        elif status == "degraded":
            if key in expected_degraded:
                warnings.append(f"{key}: expected server degradation; fallback/cache active")
            else:
                warnings.append(f"{key}: degraded source {error}".strip())
            if key in yahoo_keys and (not patch_is_current or key not in patched_keys):
                local_patch.add(key)
        elif error:
            warnings.append(f"{key}: status={status} with source error {error}".strip())
            if key in yahoo_keys and (not patch_is_current or key not in patched_keys):
                local_patch.add(key)

    for key in yahoo_keys:
        if key not in by_key:
            if patch_is_current and key in patched_keys:
                warnings.append(f"{key}: missing Yahoo fetch record remediated by local public-data patch")
            else:
                errors.append(f"{key}: missing Yahoo fetch record")
                local_patch.add(key)

    for key in policy.get("local_required", []):
        row = by_key.get(key, {})
        if not row.get("latest"):
            local_patch.add(key)

    return {
        "ok": not errors,
        "generated_at": snapshot.get("generated_at", ""),
        "fetch_mode": snapshot.get("fetch_mode", ""),
        "last_fetch_at": snapshot.get("last_fetch_at", ""),
        "last_fetch_age_hours": last_fetch_age_hours,
        "record_count": len(records),
        "errors": errors,
        "warnings": warnings,
        "local_patch_candidates": sorted(local_patch),
        "patched_keys": sorted(patched_keys) if patch_is_current else [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_sources(load_json(args.snapshot), load_json(args.policy))
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("SOURCE AUDIT PASS" if report["ok"] else "SOURCE AUDIT FAIL")
        print(f"last_fetch_at {report['last_fetch_at']} records {report['record_count']}")
        for message in report["errors"]:
            print("ERROR", message)
        for message in report["warnings"]:
            print("WARN", message)
        if report["local_patch_candidates"]:
            print("LOCAL_PATCH", " ".join(report["local_patch_candidates"]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
