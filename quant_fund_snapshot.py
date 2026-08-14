#!/usr/bin/env python3
"""Build a sanitized quant-fund snapshot for the public dashboard."""

from __future__ import annotations

import hashlib
import hmac
import csv
import json
import math
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"
PRIVATE_DIR = ROOT / ".private"
PUBLIC_SNAPSHOT = DASHBOARD / "quant_fund_snapshot.json"
PRIVATE_ENV = PRIVATE_DIR / "quant_fund.env"

FAPI_BASE = "https://fapi.binance.com"
EAPI_BASE = "https://eapi.binance.com"
SAPI_BASE = "https://api.binance.com"

DEFAULT_SYMBOL = ""


OPTIONS_SEED_POINTS = [
    {"date": "2026-06-22", "pct": 0.0021},
    {"date": "2026-06-23", "pct": -0.3457},
    {"date": "2026-06-24", "pct": 0.4213},
    {"date": "2026-06-25", "pct": -1.1163},
    {"date": "2026-06-26", "pct": -3.5040},
]


def built_in_options_seed_points() -> list[dict[str, Any]]:
    return [dict(point) for point in OPTIONS_SEED_POINTS]


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def default_start_date(today: date | None = None) -> date:
    current = today or today_utc()
    start = date(current.year, 4, 1)
    return start if current >= start else date(current.year - 1, 4, 1)


def load_env_file(path: Path = PRIVATE_ENV) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def env_date(name: str) -> date | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return parse_ymd(raw.strip())
    except ValueError:
        return None


def parse_ymd(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def signed_get(base: str, path: str, api_key: str, api_secret: str, params: dict[str, Any] | None = None) -> Any:
    query = dict(params or {})
    query["timestamp"] = int(time.time() * 1000)
    query.setdefault("recvWindow", 5000)
    encoded = urlencode(query, doseq=True)
    signature = hmac.new(api_secret.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    request = Request(f"{base}{path}?{encoded}&signature={signature}", headers={"X-MBX-APIKEY": api_key})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_futures_trades(api_key: str, api_secret: str, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    chunk_start = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    final = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc)
    # Binance limits this endpoint to seven-day windows. Full-history rebuilds
    # use the largest valid window so local VPN and server runs make fewer calls.
    max_chunk = timedelta(days=7) - timedelta(milliseconds=1)
    while chunk_start <= final:
        chunk_end = min(final, chunk_start + max_chunk)
        page_start_ms = int(chunk_start.timestamp() * 1000)
        chunk_end_ms = int(chunk_end.timestamp() * 1000)
        while page_start_ms <= chunk_end_ms:
            batch = signed_get(
                FAPI_BASE,
                "/fapi/v1/userTrades",
                api_key,
                api_secret,
                {"symbol": symbol, "startTime": page_start_ms, "endTime": chunk_end_ms, "limit": 1000},
            )
            if not isinstance(batch, list) or not batch:
                break
            trades.extend(batch)
            if len(batch) < 1000:
                break
            last_time = max(int(item.get("time", page_start_ms)) for item in batch)
            page_start_ms = last_time + 1
        chunk_start = chunk_end + timedelta(milliseconds=1)
    return trades


def require_lead_futures_context(api_key: str, api_secret: str, symbol: str) -> None:
    status = signed_get(
        SAPI_BASE,
        "/sapi/v1/copyTrading/futures/userStatus",
        api_key,
        api_secret,
    )
    if not (
        isinstance(status, dict)
        and status.get("success") is True
        and isinstance(status.get("data"), dict)
        and status["data"].get("isLeadTrader") is True
    ):
        raise ValueError("futures credentials are not a lead-trading portfolio")

    whitelist = signed_get(
        SAPI_BASE,
        "/sapi/v1/copyTrading/futures/leadSymbol",
        api_key,
        api_secret,
    )
    symbols = whitelist.get("data", []) if isinstance(whitelist, dict) and whitelist.get("success") is True else []
    if not any(
        isinstance(item, dict) and str(item.get("symbol", "")).upper() == symbol
        for item in symbols
    ):
        raise ValueError("futures symbol is not enabled for lead trading")


def load_futures_trades_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    trades: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                timestamp = int(row["time"])
                realized_pnl = float(row.get("realizedPnl", 0) or 0)
                commission = float(row.get("commission", 0) or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(realized_pnl) and math.isfinite(commission):
                trades.append(
                    {
                        "time": timestamp,
                        "realizedPnl": realized_pnl,
                        "commission": commission,
                        "commissionAsset": str(row.get("commissionAsset", "") or "").upper(),
                    }
                )
    return trades


def stable_commission_amount(trade: dict[str, Any]) -> float:
    try:
        commission = float(trade.get("commission", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(commission):
        return 0.0
    asset = str(trade.get("commissionAsset", "") or "").upper()
    if asset and asset not in {"USD", "USDT", "USDC"}:
        return 0.0
    return commission


def aggregate_futures_trade_curve(
    trades: list[dict[str, Any]],
    *,
    base_usd: float,
    start: date | None = None,
) -> list[dict[str, Any]]:
    if base_usd <= 0:
        return []
    daily: dict[str, float] = defaultdict(float)
    for trade in trades:
        try:
            pnl = float(trade.get("realizedPnl", 0) or 0)
            timestamp = int(trade["time"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(pnl):
            continue
        day = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date()
        if start and day < start:
            continue
        daily[day.isoformat()] += pnl - stable_commission_amount(trade)
    points: list[dict[str, Any]] = []
    cumulative = 0.0
    for day in sorted(daily):
        cumulative += daily[day]
        points.append({"date": day, "pct": round(cumulative / base_usd * 100, 4)})
    return points


def fetch_futures_stable_balance(api_key: str, api_secret: str) -> float:
    rows = signed_get(FAPI_BASE, "/fapi/v2/balance", api_key, api_secret)
    for item in rows if isinstance(rows, list) else []:
        if str(item.get("asset", "")).upper() == "USDC":
            return float(item.get("balance", 0) or 0) + float(item.get("crossUnPnl", 0) or 0)
    return 0.0


def fetch_option_wallet_total(api_key: str, api_secret: str) -> float:
    rows = signed_get(SAPI_BASE, "/sapi/v1/asset/wallet/balance", api_key, api_secret, {"quoteAsset": "USDT"})
    for wallet in rows if isinstance(rows, list) else []:
        if str(wallet.get("walletName", "")).lower() == "options":
            return float(wallet.get("balance", 0) or 0)
    return 0.0


def load_existing_public_snapshot(path: Path = PUBLIC_SNAPSHOT) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def build_options_percent_history(history: list[dict[str, Any]], *, base_usd: float) -> list[dict[str, Any]]:
    if base_usd <= 0:
        return []
    points: list[dict[str, Any]] = []
    for row in sorted(history, key=lambda item: item.get("date", "")):
        try:
            total = float(row["total"])
            day = str(row["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(total):
            points.append({"date": day, "pct": round((total - base_usd) / base_usd * 100, 4)})
    return points


def public_points(section: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = []
    for point in (section or {}).get("points", []) if isinstance(section, dict) else []:
        try:
            day = str(point["date"])
            pct = float(point["pct"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(pct):
            rows.append({"date": day, "pct": round(pct, 4)})
    rows.sort(key=lambda row: row["date"])
    return rows


def upsert_percent_point(points: list[dict[str, Any]], day: date, pct: float) -> list[dict[str, Any]]:
    rows = [row for row in public_points({"points": points}) if row["date"] != day.isoformat()]
    rows.append({"date": day.isoformat(), "pct": round(pct, 4)})
    rows.sort(key=lambda row: row["date"])
    return rows


def update_options_percent_points(
    existing: list[dict[str, Any]],
    *,
    day: date,
    total: float,
    base_usd: float,
    rebase_date: date | None = None,
    rebase_total_usd: float | None = None,
) -> list[dict[str, Any]]:
    if not math.isfinite(total) or base_usd <= 0:
        raise ValueError("invalid options total or base")

    rows = public_points({"points": existing})
    if rebase_date is None and rebase_total_usd is None:
        pct = (total - base_usd) / base_usd * 100
        return upsert_percent_point(rows, day, pct)
    if rebase_date is None or rebase_total_usd is None or rebase_total_usd <= 0:
        raise ValueError("incomplete options rebase configuration")

    anchor_rows = [row for row in rows if row["date"] <= rebase_date.isoformat()]
    if not anchor_rows:
        raise ValueError("missing public options rebase anchor")

    # Keep the funding-day point historical. Only subsequent PnL is scaled by
    # the new capital base, so the deposit itself cannot appear as return.
    if day <= rebase_date:
        return rows

    anchor_pct = float(anchor_rows[-1]["pct"])
    pct = anchor_pct + (total - rebase_total_usd) / base_usd * 100
    return upsert_percent_point(rows, day, pct)


def require_complete_futures_rebuild(
    existing: list[dict[str, Any]],
    rebuilt: list[dict[str, Any]],
) -> None:
    existing_rows = public_points({"points": existing})
    if not existing_rows:
        return
    rebuilt_rows = public_points({"points": rebuilt})
    if not rebuilt_rows:
        raise ValueError("empty futures API rebuild")
    existing_dates = {row["date"] for row in existing_rows}
    rebuilt_dates = {row["date"] for row in rebuilt_rows}
    if existing_dates - rebuilt_dates:
        raise ValueError("incomplete futures API rebuild")
    if rebuilt_rows[-1]["date"] < existing_rows[-1]["date"]:
        raise ValueError("stale futures API rebuild")


def merge_retained_futures_rebuild(
    existing: list[dict[str, Any]],
    rebuilt: list[dict[str, Any]],
    *,
    overlap_tolerance_pct_points: float = 0.01,
) -> list[dict[str, Any]]:
    """Merge a retention-limited API rebuild without losing verified history.

    Binance may stop returning fills older than its retained user-trade window.
    When that happens, anchor the freshly rebuilt window to the last published
    point before it, but only after every overlapping trade date and value agree.
    """
    existing_rows = public_points({"points": existing})
    rebuilt_rows = public_points({"points": rebuilt})
    if not existing_rows:
        return rebuilt_rows
    if not rebuilt_rows:
        raise ValueError("empty futures API rebuild")

    if rebuilt_rows[0]["date"] <= existing_rows[0]["date"]:
        require_complete_futures_rebuild(existing_rows, rebuilt_rows)
        return rebuilt_rows
    if rebuilt_rows[-1]["date"] < existing_rows[-1]["date"]:
        raise ValueError("stale futures API rebuild")

    first_rebuilt_date = rebuilt_rows[0]["date"]
    anchors = [row for row in existing_rows if row["date"] < first_rebuilt_date]
    if not anchors:
        raise ValueError("missing futures retention anchor")
    anchor = anchors[-1]

    rebuilt_dates = {row["date"] for row in rebuilt_rows}
    expected_overlap_dates = {
        row["date"]
        for row in existing_rows
        if first_rebuilt_date <= row["date"] <= rebuilt_rows[-1]["date"]
    }
    if expected_overlap_dates - rebuilt_dates:
        raise ValueError("incomplete futures retained-window rebuild")
    if not expected_overlap_dates:
        raise ValueError("missing futures retained-window overlap")

    aligned_rows = [
        {"date": row["date"], "pct": round(anchor["pct"] + row["pct"], 4)}
        for row in rebuilt_rows
    ]
    existing_by_date = {row["date"]: row["pct"] for row in existing_rows}
    aligned_by_date = {row["date"]: row["pct"] for row in aligned_rows}
    if any(
        abs(existing_by_date[day] - aligned_by_date[day]) > overlap_tolerance_pct_points
        for day in expected_overlap_dates
    ):
        raise ValueError("futures retained-window overlap mismatch")

    prefix = [row for row in existing_rows if row["date"] < first_rebuilt_date]
    return prefix + aligned_rows


def default_quant_fund_snapshot() -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start_date": default_start_date().isoformat(),
        "futures": {
            "label": "期货",
            "status": "missing_base",
            "points": [],
        },
        "options": {
            "label": "期权",
            "status": "missing_base",
            "points": [],
        },
        "equity": {"label": "股指", "status": "pending", "points": []},
    }


def latest_pct(points: list[dict[str, Any]]) -> float | None:
    if not points:
        return None
    try:
        return float(points[-1]["pct"])
    except (KeyError, TypeError, ValueError):
        return None


def build_snapshot() -> dict[str, Any]:
    load_env_file()
    now = datetime.now(timezone.utc)
    start = parse_ymd(os.environ.get("QUANT_FUND_START_DATE", default_start_date(now.date()).isoformat()))
    symbol = os.environ.get("QUANT_FUND_SYMBOL", DEFAULT_SYMBOL).strip().upper()
    futures_base = env_float("QUANT_FUND_FUTURES_BASE_USD")
    options_base = env_float("QUANT_FUND_OPTIONS_BASE_USD")
    options_rebase_date_raw = os.environ.get("QUANT_FUND_OPTIONS_REBASE_DATE", "").strip()
    options_rebase_total_raw = os.environ.get("QUANT_FUND_OPTIONS_REBASE_TOTAL_USD", "").strip()
    options_rebase_date = env_date("QUANT_FUND_OPTIONS_REBASE_DATE")
    options_rebase_total = env_float("QUANT_FUND_OPTIONS_REBASE_TOTAL_USD")
    options_rebase_requested = bool(options_rebase_date_raw or options_rebase_total_raw)
    options_rebase_valid = not options_rebase_requested or (
        options_rebase_date is not None and options_rebase_total is not None
    )
    futures_key = os.environ.get("BINANCE_LEAD_FUTURES_API_KEY", "")
    futures_secret = os.environ.get("BINANCE_LEAD_FUTURES_API_SECRET", "")
    option_key = os.environ.get("BINANCE_OPTION_API_KEY", "")
    option_secret = os.environ.get("BINANCE_OPTION_API_SECRET", "")
    option_futures_key = os.environ.get("BINANCE_OPTION_FUTURES_API_KEY", "")
    option_futures_secret = os.environ.get("BINANCE_OPTION_FUTURES_API_SECRET", "")
    futures_csv_raw = os.environ.get("QUANT_FUND_FUTURES_TRADES_CSV", "").strip()
    futures_csv = Path(futures_csv_raw).expanduser() if futures_csv_raw else None
    existing = load_existing_public_snapshot()
    existing_futures_points = public_points(existing.get("futures") if isinstance(existing.get("futures"), dict) else None)
    existing_options_points = public_points(existing.get("options") if isinstance(existing.get("options"), dict) else None)

    snapshot = default_quant_fund_snapshot()
    snapshot["generated_at"] = now.isoformat(timespec="seconds")
    snapshot["start_date"] = start.isoformat()

    if futures_base is None:
        snapshot["futures"] = {
            "label": "期货",
            "status": "missing_base",
            "points": existing_futures_points,
        }
    elif futures_csv and futures_csv.exists():
        trades = load_futures_trades_csv(futures_csv)
        futures_points = aggregate_futures_trade_curve(trades, base_usd=futures_base, start=start)
        snapshot["futures"] = {
            "label": "期货",
            "status": "ok" if futures_points else "no_trades",
            "points": futures_points,
            "latest_pct": latest_pct(futures_points),
        }
    elif futures_key and futures_secret and symbol:
        try:
            require_lead_futures_context(futures_key, futures_secret, symbol)
            trades = fetch_futures_trades(futures_key, futures_secret, symbol, start, now.date())
            fetched_points = aggregate_futures_trade_curve(trades, base_usd=futures_base, start=start)
            futures_points = merge_retained_futures_rebuild(existing_futures_points, fetched_points)
            snapshot["futures"] = {
                "label": "期货",
                "status": "ok" if futures_points else "no_trades",
                "points": futures_points,
                "latest_pct": latest_pct(futures_points),
            }
        except Exception as exc:  # noqa: BLE001
            snapshot["futures"] = {
                "label": "期货",
                "status": "error",
                "points": existing_futures_points,
                "error": exc.__class__.__name__,
            }
    else:
        status = "missing_symbol" if futures_key and futures_secret else "missing_credentials"
        snapshot["futures"] = {
            "label": "期货",
            "status": status,
            "points": existing_futures_points,
        }

    if options_base is None:
        option_points = existing_options_points or built_in_options_seed_points()
        option_status = "seeded" if option_points else "missing_base"
    elif not options_rebase_valid:
        option_points = existing_options_points or built_in_options_seed_points()
        option_status = "rebase_config_error"
    elif option_key and option_secret and option_futures_key and option_futures_secret:
        try:
            total = fetch_option_wallet_total(option_key, option_secret) + fetch_futures_stable_balance(
                option_futures_key,
                option_futures_secret,
            )
            option_points = update_options_percent_points(
                existing_options_points,
                day=now.date(),
                total=total,
                base_usd=options_base,
                rebase_date=options_rebase_date,
                rebase_total_usd=options_rebase_total,
            )
            option_status = "ok" if option_points else "no_history"
        except Exception as exc:  # noqa: BLE001
            option_points = existing_options_points
            option_status = "error"
            snapshot["options_error"] = exc.__class__.__name__
    else:
        option_points = existing_options_points or built_in_options_seed_points()
        option_status = "stale" if option_points else "missing_credentials"

    snapshot["options"] = {
        "label": "期权",
        "status": option_status,
        "points": option_points,
        "latest_pct": latest_pct(option_points),
    }
    snapshot["equity"] = {"label": "股指", "status": "pending", "points": []}
    return snapshot


def write_public_snapshot(snapshot: dict[str, Any], path: Path = PUBLIC_SNAPSHOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    snapshot = build_snapshot()
    write_public_snapshot(snapshot)
    print(f"wrote {PUBLIC_SNAPSHOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
