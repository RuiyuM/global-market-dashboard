#!/usr/bin/env python3
"""Build a local cross-market dashboard for bonds, FX, equity indices, and FX routes."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from fetch_wscn_ohlc import fetch_ohlc as fetch_wscn_ohlc
from fetch_investing_bond_ohlc import (
    BondSpec as InvestingSpec,
    fetch_html as fetch_investing_html,
    rows_from_html as rows_from_investing_html,
)


ROOT = Path(__file__).resolve().parent
LOCAL_DATA = ROOT / "data"
DASHBOARD = ROOT / "dashboard"
DASHBOARD_DATA = DASHBOARD / "data"
SNAPSHOT_JSON = DASHBOARD / "latest_market_snapshot.json"
HTML_OUT = DASHBOARD / "index.html"
DEFAULT_FX_FLOW_CODE = ROOT / "fx_flow_logic.py"
USER_FX_FLOW_CODE = Path(os.environ.get("FX_FLOW_CODE_PATH", str(DEFAULT_FX_FLOW_CODE)))


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    label: str
    asset_class: str
    source: str
    symbol: str
    cache_file: str
    local_file: str | None = None
    stale_days: int = 7


WSCN_SPECS = [
    SeriesSpec("US_2Y", "美国2年国债", "bond", "wscn", "US2YR.OTC", "US_2Y.csv", "US2YR_OTC_1D_ohlc.csv"),
    SeriesSpec("US_10Y", "美国10年国债", "bond", "wscn", "US10YR.OTC", "US_10Y.csv", "US10YR_OTC_1D_ohlc.csv"),
    SeriesSpec("CN_2Y", "中国2年国债", "bond", "wscn", "CN2YR.OTC", "CN_2Y.csv", "CN2YR_OTC_1D_ohlc.csv"),
    SeriesSpec("CN_10Y", "中国10年国债", "bond", "wscn", "CN10YR.OTC", "CN_10Y.csv", "CN10YR_OTC_1D_ohlc.csv"),
    SeriesSpec("USDCNY", "美元/人民币", "fx", "wscn", "USDCNY.OTC", "USDCNY.csv", "USDCNY_OTC_1D_ohlc.csv"),
    SeriesSpec("JPYCNY", "日元/人民币", "fx", "wscn", "JPYCNY.OTC", "JPYCNY.csv", "JPYCNY_OTC_1D_ohlc.csv"),
    SeriesSpec("USDJPY", "美元/日元", "fx", "wscn", "USDJPY.OTC", "USDJPY.csv", "USDJPY_OTC_1D_ohlc.csv"),
    SeriesSpec("EURCNY", "欧元/人民币", "fx", "wscn", "EURCNY.OTC", "EURCNY.csv", None),
    SeriesSpec("EURJPY", "欧元/日元", "fx", "wscn", "EURJPY.OTC", "EURJPY.csv", None),
    SeriesSpec("EURUSD", "欧元/美元", "fx", "wscn", "EURUSD.OTC", "EURUSD.csv", None),
    SeriesSpec("USDRUB", "美元/卢布", "fx", "wscn", "USDRUB.OTC", "USDRUB.csv", None),
    SeriesSpec("CN_EQUITY", "上证综指", "equity", "wscn", "000001.SS", "CN_EQUITY.csv", "000001_SS_1D_ohlc.csv"),
]


INVESTING_SPECS: list[tuple[SeriesSpec, InvestingSpec]] = [
    (
        SeriesSpec("JP_2Y", "日本2年国债", "bond", "investing", "JP2YT=XX", "JP_2Y.csv", "JP2YR_INVESTING_1D_ohlc.csv"),
        InvestingSpec("JP2Y", "23893", "JP2YT=XX", "japan-2-year-bond-yield-historical-data", "Japan 2-Year Bond Yield Historical Data", "JP2YR_INVESTING_1D_ohlc.csv"),
    ),
    (
        SeriesSpec("JP_10Y", "日本10年国债", "bond", "investing", "JP10YT=RR", "JP_10Y.csv", "JP10YR_OTC_1D_ohlc.csv"),
        InvestingSpec("JP10Y", "23901", "JP10YT=RR", "japan-10-year-bond-yield-historical-data", "Japan 10-Year Bond Yield Historical Data", "JP10YR_INVESTING_1D_ohlc.csv"),
    ),
    (
        SeriesSpec("DE_2Y", "德国2年国债", "bond", "investing", "DE2YT=RR", "DE_2Y.csv"),
        InvestingSpec("DE2Y", "23685", "DE2YT=RR", "germany-2-year-bond-yield-historical-data", "Germany 2-Year Bond Yield Historical Data", "DE2YR_INVESTING_1D_ohlc.csv"),
    ),
    (
        SeriesSpec("DE_10Y", "德国10年国债", "bond", "investing", "DE10YT=RR", "DE_10Y.csv"),
        InvestingSpec("DE10Y", "23693", "DE10YT=RR", "germany-10-year-bond-yield-historical-data", "Germany 10-Year Bond Yield Historical Data", "DE10YR_INVESTING_1D_ohlc.csv"),
    ),
    (
        SeriesSpec("RU_2Y", "俄罗斯2年国债", "bond", "investing", "RU2YT=RR", "RU_2Y.csv"),
        InvestingSpec("RU2Y", "23971", "RU2YT=RR", "russia-2-year-bond-yield-historical-data", "Russia 2-Year Bond Yield Historical Data", "RU2YR_INVESTING_1D_ohlc.csv"),
    ),
    (
        SeriesSpec("RU_10Y", "俄罗斯10年国债", "bond", "investing", "RU10YT=RR", "RU_10Y.csv"),
        InvestingSpec("RU10Y", "23974", "RU10YT=RR", "russia-10-year-bond-yield-historical-data", "Russia 10-Year Bond Yield Historical Data", "RU10YR_INVESTING_1D_ohlc.csv"),
    ),
    (
        SeriesSpec("KR_2Y", "韩国2年国债", "bond", "investing", "KR2YT=RR", "KR_2Y.csv"),
        InvestingSpec("KR2Y", "29295", "KR2YT=RR", "south-korea-2-year-bond-yield-historical-data", "South Korea 2-Year Bond Yield Historical Data", "KR2YR_INVESTING_1D_ohlc.csv"),
    ),
    (
        SeriesSpec("KR_10Y", "韩国10年国债", "bond", "investing", "KR10YT=RR", "KR_10Y.csv"),
        InvestingSpec("KR10Y", "29292", "KR10YT=RR", "south-korea-10-year-bond-yield-historical-data", "South Korea 10-Year Bond Yield Historical Data", "KR10YR_INVESTING_1D_ohlc.csv"),
    ),
    (
        SeriesSpec("RU_EQUITY", "俄罗斯MOEX", "equity", "investing", "IMOEX", "RU_EQUITY.csv"),
        InvestingSpec("RU_EQUITY", "13666", "IMOEX", "mcx-historical-data", "MOEX Russia Index Historical Data", "RU_EQUITY_INVESTING_1D_ohlc.csv", path_prefix="indices"),
    ),
]


YAHOO_SPECS = [
    SeriesSpec("US_EQUITY", "标普500", "equity", "yahoo", "^GSPC", "US_EQUITY.csv", "SP500_YAHOO_1D_ohlc.csv"),
    SeriesSpec("JP_EQUITY", "日经225", "equity", "yahoo", "^N225", "JP_EQUITY.csv", "NIKKEI225_YAHOO_1D_ohlc.csv"),
    SeriesSpec("DE_EQUITY", "德国DAX", "equity", "yahoo", "^GDAXI", "DE_EQUITY.csv", None),
    SeriesSpec("KR_EQUITY", "韩国KOSPI", "equity", "yahoo", "^KS11", "KR_EQUITY.csv", None),
    SeriesSpec("KRWCNY", "韩元/人民币", "fx", "yahoo", "KRWCNY=X", "KRWCNY.csv", None),
    SeriesSpec("USDKRW", "美元/韩元", "fx", "yahoo", "USDKRW=X", "USDKRW.csv", None),
    SeriesSpec("RUBCNY_YAHOO", "卢布/人民币", "fx", "yahoo", "RUBCNY=X", "RUBCNY_YAHOO.csv", None),
    SeriesSpec("RUBJPY_YAHOO", "卢布/日元", "fx", "yahoo", "RUBJPY=X", "RUBJPY_YAHOO.csv", None),
    SeriesSpec("USDRUB_YAHOO", "美元/卢布", "fx", "yahoo", "USDRUB=X", "USDRUB_YAHOO.csv", None),
]


COUNTRIES = [
    {"code": "US", "name": "美国", "ccy": "USD", "bond_2y": "US_2Y", "bond_10y": "US_10Y", "equity": "US_EQUITY", "fx": "USDCNY"},
    {"code": "CN", "name": "中国", "ccy": "CNY", "bond_2y": "CN_2Y", "bond_10y": "CN_10Y", "equity": "CN_EQUITY", "fx": "CNY_BASE"},
    {"code": "JP", "name": "日本", "ccy": "JPY", "bond_2y": "JP_2Y", "bond_10y": "JP_10Y", "equity": "JP_EQUITY", "fx": "JPYCNY"},
    {"code": "DE", "name": "德国", "ccy": "EUR", "bond_2y": "DE_2Y", "bond_10y": "DE_10Y", "equity": "DE_EQUITY", "fx": "EURCNY"},
    {"code": "RU", "name": "俄罗斯", "ccy": "RUB", "bond_2y": "RU_2Y", "bond_10y": "RU_10Y", "equity": "RU_EQUITY", "fx": "RUBCNY"},
    {"code": "KR", "name": "韩国", "ccy": "KRW", "bond_2y": "KR_2Y", "bond_10y": "KR_10Y", "equity": "KR_EQUITY", "fx": "KRWCNY"},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", dest="fetch", action="store_true", default=True, help="Fetch latest WSCN/Yahoo data before rendering.")
    parser.add_argument("--no-fetch", dest="fetch", action="store_false", help="Use cached/local CSV files only.")
    parser.add_argument("--lookback-days", type=int, default=220, help="Yahoo fetch lookback window.")
    parser.add_argument("--wscn-count", type=int, default=260, help="WSCN rows per series.")
    parser.add_argument("--sleep-sec", type=float, default=0.15)
    return parser.parse_args()


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def date_to_epoch(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp())


def fetch_yahoo_ohlc(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "period1": date_to_epoch(start),
            "period2": date_to_epoch(end + timedelta(days=1)),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{query}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,*/*"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo chart error for {symbol}: {chart['error']}")
    result = (chart.get("result") or [None])[0]
    if not result:
        return []

    timestamps = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        open_px = value_at(quote_data.get("open"), index)
        high_px = value_at(quote_data.get("high"), index)
        low_px = value_at(quote_data.get("low"), index)
        close_px = value_at(quote_data.get("close"), index)
        volume = value_at(quote_data.get("volume"), index)
        if None in {open_px, high_px, low_px, close_px}:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date().isoformat(),
                "timestamp": int(timestamp),
                "open": float(open_px),
                "high": float(high_px),
                "low": float(low_px),
                "close": float(close_px),
                "volume": int(volume) if volume is not None else "",
                "source_symbol": symbol,
                "source": "Yahoo Finance chart API",
            }
        )
    return rows


def value_at(values: Any, index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def write_ohlc(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "timestamp", "open", "high", "low", "close", "volume", "source_symbol", "source"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fetch_all(args: argparse.Namespace) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    DASHBOARD_DATA.mkdir(parents=True, exist_ok=True)

    for spec in WSCN_SPECS:
        path = DASHBOARD_DATA / spec.cache_file
        record = {"key": spec.key, "source": spec.source, "symbol": spec.symbol, "status": "pending", "file": str(path), "error": ""}
        try:
            rows = fetch_wscn_ohlc(spec.symbol, "1D", args.wscn_count, min(args.wscn_count, 1000))
            write_ohlc(path, rows)
            record.update({"status": "ok", "rows": str(len(rows)), "latest": rows[-1]["date"] if rows else ""})
        except Exception as exc:
            record.update({"status": "error", "error": str(exc)})
        records.append(record)
        if args.sleep_sec:
            time.sleep(args.sleep_sec)

    end = today_utc()
    start = end - timedelta(days=args.lookback_days)
    for spec in YAHOO_SPECS:
        path = DASHBOARD_DATA / spec.cache_file
        record = {"key": spec.key, "source": spec.source, "symbol": spec.symbol, "status": "pending", "file": str(path), "error": ""}
        try:
            rows = fetch_yahoo_ohlc(spec.symbol, start, end)
            if rows:
                write_ohlc(path, rows)
            record.update({"status": "ok" if rows else "empty", "rows": str(len(rows)), "latest": rows[-1]["date"] if rows else ""})
        except Exception as exc:
            record.update({"status": "error", "error": str(exc)})
        records.append(record)
        if args.sleep_sec:
            time.sleep(args.sleep_sec)

    for series_spec, investing_spec in INVESTING_SPECS:
        path = DASHBOARD_DATA / series_spec.cache_file
        record = {
            "key": series_spec.key,
            "source": series_spec.source,
            "symbol": series_spec.symbol,
            "status": "pending",
            "file": str(path),
            "error": "",
        }
        try:
            rows = rows_from_investing_html(fetch_investing_html(investing_spec, start, end))
            write_ohlc(path, rows)
            record.update({"status": "ok" if rows else "empty", "rows": str(len(rows)), "latest": rows[-1]["date"] if rows else ""})
        except Exception as exc:
            record.update({"status": "error", "error": str(exc)})
        records.append(record)
        if args.sleep_sec:
            time.sleep(args.sleep_sec)

    return records


def read_series(spec: SeriesSpec) -> list[dict[str, Any]]:
    paths = [DASHBOARD_DATA / spec.cache_file]
    if spec.local_file:
        paths.append(LOCAL_DATA / spec.local_file)

    for path in paths:
        if path.exists():
            rows = read_ohlc(path)
            if rows:
                return rows
    return []


def read_ohlc(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            date_key = "date" if "date" in row else "observation_date"
            close_key = "close" if "close" in row else next((key for key in row if key != date_key), "")
            if not close_key:
                continue
            try:
                parsed_date = datetime.strptime(row[date_key], "%Y-%m-%d").date()
                close = float(row[close_key])
                open_px = float(row.get("open") or close)
                high = float(row.get("high") or close)
                low = float(row.get("low") or close)
            except (ValueError, TypeError):
                continue
            rows.append({"date": parsed_date, "open": open_px, "high": high, "low": low, "close": close})
    rows.sort(key=lambda row: row["date"])
    dedup: dict[date, dict[str, Any]] = {}
    for row in rows:
        dedup[row["date"]] = row
    return [dedup[key] for key in sorted(dedup)]


def constant_series(key: str, value: float, start: date, end: date) -> list[dict[str, Any]]:
    rows = []
    cursor = start
    while cursor <= end:
        rows.append({"date": cursor, "open": value, "high": value, "low": value, "close": value})
        cursor += timedelta(days=1)
    return rows


def forward_fill_map(rows: list[dict[str, Any]]) -> dict[date, float]:
    return {row["date"]: row["close"] for row in rows}


def derived_ratio(key: str, numerator: list[dict[str, Any]], denominator: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    if not numerator or not denominator:
        return []
    dates = sorted({row["date"] for row in numerator} | {row["date"] for row in denominator})
    numerator_map = forward_fill_map(numerator)
    denominator_map = forward_fill_map(denominator)
    n_last = None
    d_last = None
    rows = []
    for dt in dates:
        if dt in numerator_map:
            n_last = numerator_map[dt]
        if dt in denominator_map:
            d_last = denominator_map[dt]
        if n_last is None or d_last in {None, 0}:
            continue
        value = n_last / d_last
        rows.append({"date": dt, "open": value, "high": value, "low": value, "close": value, "derived": label})
    return rows


def derived_difference(key: str, left: list[dict[str, Any]], right: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    if not left or not right:
        return []
    dates = sorted({row["date"] for row in left} | {row["date"] for row in right})
    left_map = forward_fill_map(left)
    right_map = forward_fill_map(right)
    left_last = None
    right_last = None
    rows = []
    for dt in dates:
        if dt in left_map:
            left_last = left_map[dt]
        if dt in right_map:
            right_last = right_map[dt]
        if left_last is None or right_last is None:
            continue
        value = left_last - right_last
        rows.append({"date": dt, "open": value, "high": value, "low": value, "close": value, "derived": label})
    return rows


def load_all_series() -> tuple[dict[str, list[dict[str, Any]]], dict[str, SeriesSpec]]:
    investing_series_specs = [series_spec for series_spec, _ in INVESTING_SPECS]
    specs = {spec.key: spec for spec in [*WSCN_SPECS, *YAHOO_SPECS, *investing_series_specs]}
    series = {key: read_series(spec) for key, spec in specs.items()}

    # Base currency and derived crosses.
    all_dates = [row["date"] for rows in series.values() for row in rows]
    start = min(all_dates) if all_dates else today_utc() - timedelta(days=60)
    end = max(all_dates) if all_dates else today_utc()
    base_spec = SeriesSpec("CNY_BASE", "人民币基准", "fx", "derived", "CNY", "CNY_BASE.csv")
    specs[base_spec.key] = base_spec
    series[base_spec.key] = constant_series("CNY_BASE", 1.0, start, end)

    usdcny = series.get("USDCNY", [])
    jpycny = series.get("JPYCNY", [])
    usd_jpy = series.get("USDJPY", [])
    usdrub = series.get("USDRUB") or series.get("USDRUB_YAHOO", [])

    rubcny = derived_ratio("RUBCNY", usdcny, usdrub, "USDCNY / USDRUB")
    if not enough_recent_history(rubcny, 30):
        rubcny = series.get("RUBCNY_YAHOO", [])
    specs["RUBCNY"] = SeriesSpec("RUBCNY", "卢布/人民币", "fx", "derived", "USDCNY/USDRUB", "RUBCNY.csv")
    series["RUBCNY"] = rubcny

    rubjpy = derived_ratio("RUBJPY", usd_jpy, usdrub, "USDJPY / USDRUB")
    if not enough_recent_history(rubjpy, 30):
        rubjpy = series.get("RUBJPY_YAHOO", [])
    specs["RUBJPY"] = SeriesSpec("RUBJPY", "卢布/日元", "fx", "derived", "USDJPY/USDRUB", "RUBJPY.csv")
    series["RUBJPY"] = rubjpy

    cnyjpy = derived_ratio("CNYJPY", series["CNY_BASE"], jpycny, "1 / JPYCNY")
    specs["CNYJPY"] = SeriesSpec("CNYJPY", "人民币/日元", "fx", "derived", "1/JPYCNY", "CNYJPY.csv")
    series["CNYJPY"] = cnyjpy

    for country in COUNTRIES:
        curve_key = f"{country['code']}_10Y2Y"
        bond_10y = series.get(country["bond_10y"], [])
        bond_2y = series.get(country["bond_2y"], [])
        specs[curve_key] = SeriesSpec(
            curve_key,
            f"{country['name']}10Y-2Y曲线",
            "bond_curve",
            "derived",
            f"{country['bond_10y']}-{country['bond_2y']}",
            f"{curve_key}.csv",
        )
        series[curve_key] = derived_difference(curve_key, bond_10y, bond_2y, "10Y - 2Y")

    return series, specs


def enough_recent_history(rows: list[dict[str, Any]], days: int) -> bool:
    latest = latest_row(rows)
    if not latest:
        return False
    return at_or_before(rows, latest["date"] - timedelta(days=days)) is not None


def at_or_before(rows: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    prior = None
    for row in rows:
        if row["date"] <= target:
            prior = row
        else:
            break
    return prior


def latest_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[-1] if rows else None


def change(rows: list[dict[str, Any]], days: int | None, *, unit: str) -> dict[str, Any] | None:
    latest = latest_row(rows)
    if not latest:
        return None
    if days is None:
        if len(rows) < 2:
            return None
        base = rows[-2]
    else:
        base = at_or_before(rows, latest["date"] - timedelta(days=days))
    if not base or base["close"] == 0:
        return None

    diff = latest["close"] - base["close"]
    if unit == "bp":
        value = diff * 100
    else:
        value = math.log(latest["close"] / base["close"]) * 100
    return {"value": value, "base_date": base["date"].isoformat(), "latest_date": latest["date"].isoformat()}


def prior_row_before(rows: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    prior = None
    for row in rows:
        if row["date"] < target:
            prior = row
        else:
            break
    return prior


def window_move(
    rows: list[dict[str, Any]],
    end_date: date,
    days: int,
    *,
    unit: str,
) -> dict[str, Any] | None:
    end = at_or_before(rows, end_date)
    if not end:
        return None

    if days == 1:
        base = prior_row_before(rows, end["date"])
    else:
        base = at_or_before(rows, end["date"] - timedelta(days=days))
    if not base or base["close"] == 0 or base["date"] >= end["date"]:
        return None

    if unit == "bp":
        delta = (end["close"] - base["close"]) * 100
    else:
        delta = math.log(end["close"] / base["close"]) * 100

    span_days = max(1, (end["date"] - base["date"]).days)
    return {
        "delta": delta,
        "velocity": delta / span_days,
        "base_date": base["date"],
        "end_date": end["date"],
        "span_days": span_days,
    }


def derivative_metrics(rows: list[dict[str, Any]], days: int, *, unit: str) -> dict[str, Any] | None:
    latest = latest_row(rows)
    if not latest:
        return None

    current = window_move(rows, latest["date"], days, unit=unit)
    if not current:
        return None
    previous = window_move(rows, current["base_date"], days, unit=unit)
    if not previous:
        return None

    mid_span = max(1.0, (current["span_days"] + previous["span_days"]) / 2)
    acceleration = (current["velocity"] - previous["velocity"]) / mid_span
    signal = derivative_signal(current["velocity"], previous["velocity"], acceleration)
    return {
        "window": f"{days}D",
        "unit": unit,
        "delta": current["delta"],
        "velocity": current["velocity"],
        "previous_velocity": previous["velocity"],
        "acceleration": acceleration,
        "base_date": current["base_date"].isoformat(),
        "end_date": current["end_date"].isoformat(),
        "previous_base_date": previous["base_date"].isoformat(),
        "previous_end_date": previous["end_date"].isoformat(),
        "span_days": current["span_days"],
        "previous_span_days": previous["span_days"],
        "signal": signal,
    }


def derivative_signal(velocity: float, previous_velocity: float, acceleration: float) -> str:
    if velocity > 0 and previous_velocity <= 0:
        return "转上"
    if velocity < 0 and previous_velocity >= 0:
        return "转下"
    if velocity > 0 and acceleration > 0:
        return "上行加速"
    if velocity > 0 and acceleration < 0:
        return "上行减速"
    if velocity < 0 and acceleration < 0:
        return "下行加速"
    if velocity < 0 and acceleration > 0:
        return "下行减速"
    return "持平"


def build_second_order_monitor(
    series: dict[str, list[dict[str, Any]]],
    specs: dict[str, SeriesSpec],
) -> list[dict[str, Any]]:
    rows = []
    windows = [1, 7, 30]
    for country in COUNTRIES:
        instruments = [
            ("股指", country["equity"], "pct"),
            ("外汇", country["fx"], "pct"),
            ("债券", country["bond_2y"], "bp"),
            ("债券", country["bond_10y"], "bp"),
            ("债券曲线", f"{country['code']}_10Y2Y", "bp"),
        ]
        for group, key, unit in instruments:
            spec = specs.get(key)
            metrics = {f"{days}D": derivative_metrics(series.get(key, []), days, unit=unit) for days in windows}
            item = {
                "country": country["name"],
                "code": country["code"],
                "group": group,
                "key": key,
                "label": spec.label if spec else key,
                "unit": unit,
                "metrics": metrics,
                "ohlc": recent_ohlc_rows(series.get(key, []), limit=90),
                "chart_type": "ohlc",
            }
            if group == "债券曲线":
                bond_2y_spec = specs.get(country["bond_2y"])
                bond_10y_spec = specs.get(country["bond_10y"])
                item["chart_type"] = "bond_curve"
                item["curve"] = {
                    "bond_2y_label": bond_2y_spec.label if bond_2y_spec else country["bond_2y"],
                    "bond_10y_label": bond_10y_spec.label if bond_10y_spec else country["bond_10y"],
                    "rows": recent_bond_curve_rows(
                        series.get(country["bond_2y"], []),
                        series.get(country["bond_10y"], []),
                        limit=90,
                    ),
                }
            rows.append(item)
    return rows


def recent_ohlc_rows(rows: list[dict[str, Any]], limit: int = 90) -> list[dict[str, Any]]:
    out = []
    for row in rows[-limit:]:
        out.append(
            {
                "date": row["date"].isoformat(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
        )
    return out


def recent_bond_curve_rows(
    bond_2y: list[dict[str, Any]],
    bond_10y: list[dict[str, Any]],
    limit: int = 90,
) -> list[dict[str, Any]]:
    if not bond_2y or not bond_10y:
        return []

    dates = sorted({row["date"] for row in bond_2y} | {row["date"] for row in bond_10y})
    map_2y = forward_fill_map(bond_2y)
    map_10y = forward_fill_map(bond_10y)
    last_2y = None
    last_10y = None
    rows = []
    for dt in dates:
        if dt in map_2y:
            last_2y = map_2y[dt]
        if dt in map_10y:
            last_10y = map_10y[dt]
        if last_2y is None or last_10y is None:
            continue
        spread_bp = (last_10y - last_2y) * 100
        rows.append(
            {
                "date": dt.isoformat(),
                "bond_2y": last_2y,
                "bond_10y": last_10y,
                "spread_bp": spread_bp,
                "positive": last_10y >= last_2y,
            }
        )
    return rows[-limit:]


def average_abs_vol(rows: list[dict[str, Any]], *, unit: str, periods: int) -> float | None:
    if len(rows) < 2:
        return None
    latest = rows[-(periods + 1) :]
    values = []
    for previous, current in zip(latest, latest[1:]):
        if previous["close"] == 0:
            continue
        if unit == "bp":
            values.append(abs(current["close"] - previous["close"]) * 100)
        else:
            values.append(abs(math.log(current["close"] / previous["close"])) * 100)
    return statistics.mean(values) if values else None


def volatility_windows(rows: list[dict[str, Any]], *, unit: str) -> dict[str, float | None]:
    return {
        "7D": average_abs_vol(rows, unit=unit, periods=7),
        "30D": average_abs_vol(rows, unit=unit, periods=30),
    }


def series_summary(key: str, rows: list[dict[str, Any]], unit: str, stale_days: int = 7) -> dict[str, Any]:
    latest = latest_row(rows)
    if not latest:
        return {"key": key, "available": False, "latest": None, "date": "", "stale": True}
    age = (today_utc() - latest["date"]).days
    return {
        "key": key,
        "available": True,
        "latest": latest["close"],
        "date": latest["date"].isoformat(),
        "age_days": age,
        "stale": age > stale_days,
        "chg_1d": change(rows, None, unit=unit),
        "chg_7d": change(rows, 7, unit=unit),
        "chg_14d": change(rows, 14, unit=unit),
        "chg_30d": change(rows, 30, unit=unit),
        "week_avg_abs_vol": average_abs_vol(rows, unit=unit, periods=7),
        "avg_abs_vol": volatility_windows(rows, unit=unit),
    }


def build_country_rows(series: dict[str, list[dict[str, Any]]], specs: dict[str, SeriesSpec]) -> list[dict[str, Any]]:
    rows = []
    for country in COUNTRIES:
        row = {"country": country["name"], "code": country["code"], "ccy": country["ccy"]}
        for field, unit in [("bond_2y", "bp"), ("bond_10y", "bp"), ("equity", "pct"), ("fx", "pct")]:
            key = country[field]
            spec = specs.get(key)
            row[field] = {
                "key": key,
                "label": spec.label if spec else key,
                "summary": series_summary(key, series.get(key, []), unit, stale_days=spec.stale_days if spec else 7),
            }
        rows.append(row)
    return rows


def asset_class_vol(country_rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {
        "equity": ("股指", "equity", "pct"),
        "bond": ("债市", ("bond_2y", "bond_10y"), "bp"),
        "fx": ("汇率", "fx", "pct"),
    }
    result = {}
    for key, (label, fields, unit) in groups.items():
        fields_tuple = fields if isinstance(fields, tuple) else (fields,)
        windows = {}
        for period in ["7D", "30D"]:
            values = []
            for row in country_rows:
                for field in fields_tuple:
                    summary = row[field]["summary"]
                    value = (summary.get("avg_abs_vol") or {}).get(period)
                    if value is not None and not summary.get("stale"):
                        values.append(value)
            windows[period] = {"value": statistics.mean(values) if values else None, "count": len(values)}
        result[key] = {
            "label": label,
            "unit": unit,
            "value": windows["7D"]["value"],
            "count": windows["7D"]["count"],
            "windows": windows,
        }
    return result


def summary_volatility(summary: dict[str, Any], period: str) -> float | None:
    return (summary.get("avg_abs_vol") or {}).get(period)


def volatility_rankings(country_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "bond": {"label": "债市", "unit": "bp", "fields": ("bond_2y", "bond_10y")},
        "equity": {"label": "股指", "unit": "pct", "fields": ("equity",)},
        "fx": {"label": "汇率", "unit": "pct", "fields": ("fx",)},
    }
    rankings: dict[str, list[dict[str, Any]]] = {}
    for key, spec in groups.items():
        rows = []
        for country in country_rows:
            windows = {}
            sample_counts = {}
            for period in ["7D", "30D"]:
                values = []
                for field in spec["fields"]:
                    summary = country[field]["summary"]
                    value = summary_volatility(summary, period)
                    if value is not None and not summary.get("stale"):
                        values.append(value)
                windows[period] = statistics.mean(values) if values else None
                sample_counts[period] = len(values)

            if windows["7D"] is None:
                continue
            rows.append(
                {
                    "country": country["country"],
                    "ccy": country["ccy"],
                    "label": spec["label"],
                    "unit": spec["unit"],
                    "windows": windows,
                    "sample_counts": sample_counts,
                }
            )

        rows.sort(key=lambda item: item["windows"]["7D"], reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        rankings[key] = rows
    return rankings


def load_user_fx_flow_logic() -> Any:
    if not USER_FX_FLOW_CODE.exists():
        raise FileNotFoundError(f"missing user FX flow code: {USER_FX_FLOW_CODE}")
    loader = SourceFileLoader("user_fx_flow_logic", str(USER_FX_FLOW_CODE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"cannot create import spec for {USER_FX_FLOW_CODE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


USER_FX_FLOW_LOGIC = load_user_fx_flow_logic()


def route_to_dict(route: Any) -> dict[str, Any] | None:
    if route is None:
        return None
    return {
        "x": route.x,
        "y": route.y,
        "z": route.z,
        "label": route.label,
        "score": route.score,
        "status": route.status,
    }


def direct_row_to_dict(row: Any) -> dict[str, Any]:
    return {"base": row.base, "quote": row.quote, "old": row.old, "new": row.new, "q": row.q}


def analyze_fx_logic_with_user_code(changes: list[dict[str, Any]]) -> dict[str, Any]:
    result = USER_FX_FLOW_LOGIC.analyze_fx_logic(changes, method="log_percent", eps=1e-9)
    return {
        "method": result["method"],
        "currencies": result["currencies"],
        "direct_rows": [direct_row_to_dict(row) for row in result["direct_rows"]],
        "routes": [route_to_dict(route) for route in sorted(result["routes"], key=lambda route: route.score, reverse=True)],
        "best_route": route_to_dict(result["best_route"]),
        "strength": result["strength"],
        "ranking": result["ranking"],
        "triangle_residuals": result["triangle_residuals"],
        "missing_routes": result["missing_routes"],
        "source_code": str(USER_FX_FLOW_CODE),
    }


def rate_pair_change(
    series: dict[str, list[dict[str, Any]]],
    key: str,
    pair: str,
    days: int | None,
    *,
    offset_days: int = 0,
    offset_observations: int = 0,
) -> dict[str, Any] | None:
    rows = series.get(key, [])
    if days is None:
        end_index = len(rows) - 1 - offset_observations
        base_index = end_index - 1
        if base_index < 0 or end_index >= len(rows):
            return None
        base = rows[base_index]
        end = rows[end_index]
    else:
        latest = latest_row(rows)
        if not latest:
            return None
        end_target = latest["date"] - timedelta(days=offset_days)
        base_target = latest["date"] - timedelta(days=offset_days + days)
        end = latest if offset_days == 0 else at_or_before(rows, end_target)
        base = at_or_before(rows, base_target)
        if not end or not base or base["date"] >= end["date"]:
            return None

    if base["close"] <= 0 or end["close"] <= 0:
        return None
    return {
        "pair": pair,
        "old": base["close"],
        "new": end["close"],
        "base_date": base["date"].isoformat(),
        "latest_date": end["date"].isoformat(),
        "source_key": key,
    }


def build_flow_sections(series: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    triads = [
        {"name": "中日美", "pairs": [("USDCNY", "美中"), ("JPYCNY", "日中"), ("USDJPY", "美日")]},
        {"name": "中德美", "pairs": [("USDCNY", "美中"), ("EURCNY", "德中"), ("EURUSD", "德美")]},
        {"name": "中俄美", "pairs": [("USDCNY", "美中"), ("RUBCNY", "俄中"), ("USDRUB", "美俄")]},
    ]
    periods = [
        {"label": "当日", "days": None, "offset_days": 0, "offset_observations": 0},
        {"label": "上日", "days": None, "offset_days": 0, "offset_observations": 1},
        {"label": "当周", "days": 7, "offset_days": 0, "offset_observations": 0},
        {"label": "上周", "days": 7, "offset_days": 7, "offset_observations": 0},
        {"label": "当月", "days": 30, "offset_days": 0, "offset_observations": 0},
        {"label": "上月", "days": 30, "offset_days": 30, "offset_observations": 0},
    ]
    sections = []
    for triad in triads:
        period_rows = []
        for period in periods:
            changes = []
            missing = []
            for key, pair in triad["pairs"]:
                item = rate_pair_change(
                    series,
                    key,
                    pair,
                    period["days"],
                    offset_days=period["offset_days"],
                    offset_observations=period["offset_observations"],
                )
                if item:
                    changes.append(item)
                else:
                    missing.append(key)
            if len(changes) == 3:
                try:
                    result = analyze_fx_logic_with_user_code(changes)
                    period_rows.append({"period": period["label"], "changes": changes, "result": result, "missing": []})
                except Exception as exc:
                    period_rows.append({"period": period["label"], "changes": changes, "result": None, "missing": [str(exc)]})
            else:
                period_rows.append({"period": period["label"], "changes": changes, "result": None, "missing": missing})
        sections.append({"name": triad["name"], "periods": period_rows})
    return sections


def build_snapshot(fetch_records: list[dict[str, str]]) -> dict[str, Any]:
    series, specs = load_all_series()
    countries = build_country_rows(series, specs)
    snapshot = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "countries": countries,
        "asset_class_vol": asset_class_vol(countries),
        "volatility_rankings": volatility_rankings(countries),
        "second_order_monitor": build_second_order_monitor(series, specs),
        "fx_flows": build_flow_sections(series),
        "series_status": build_series_status(series, specs),
        "fetch_records": fetch_records,
        "notes": [
            "债券变化单位为 bp；股指和汇率变化单位为对数百分比。",
            "一阶速度 = 当前窗口变化 / 实际间隔天数；二阶加速度 = 当前一阶速度相对上一段同长度窗口的速度变化 / 平均间隔天数。",
            "7D/30D 波动率 = 对应窗口相邻交易观测的平均绝对日变化；债券单位 bp/日，股指和汇率单位 %/日。",
            f"三币种资金流向直接调用用户提供代码：{USER_FX_FLOW_CODE}",
            "WSCN 缺口优先用 Yahoo；俄/韩债券若无可靠日线会显示缺失。",
        ],
    }
    return snapshot


def build_series_status(series: dict[str, list[dict[str, Any]]], specs: dict[str, SeriesSpec]) -> list[dict[str, Any]]:
    rows = []
    for key in sorted(specs):
        spec = specs[key]
        latest = latest_row(series.get(key, []))
        rows.append(
            {
                "key": key,
                "label": spec.label,
                "asset_class": spec.asset_class,
                "source": spec.source,
                "symbol": spec.symbol,
                "latest_date": latest["date"].isoformat() if latest else "",
                "latest": latest["close"] if latest else None,
                "stale": (today_utc() - latest["date"]).days > spec.stale_days if latest else True,
            }
        )
    return rows


def fmt_value(value: Any, digits: int = 3) -> str:
    if value is None:
        return "缺失"
    if isinstance(value, float):
        if math.isnan(value):
            return "缺失"
        return f"{value:,.{digits}f}"
    return str(value)


def fmt_change(summary: dict[str, Any], key: str, unit: str) -> str:
    item = summary.get(key)
    if not item:
        return '<span class="muted">缺失</span>'
    value = item["value"]
    cls = "pos" if value > 0 else "neg" if value < 0 else "flat"
    suffix = "bp" if unit == "bp" else "%"
    return f'<span class="{cls}">{value:+.2f}{suffix}</span>'


def fmt_volatility_value(value: float | None, unit: str) -> str:
    if value is None:
        return "缺失"
    suffix = "bp/日" if unit == "bp" else "%/日"
    return f"{value:.2f}{suffix}"


def fmt_asset_volatility(summary: dict[str, Any], unit: str) -> str:
    windows = summary.get("avg_abs_vol") or {}
    return (
        '<div class="asset-vol">'
        f'<span>7D 波动 {escape(fmt_volatility_value(windows.get("7D"), unit))}</span>'
        f'<span>30D 波动 {escape(fmt_volatility_value(windows.get("30D"), unit))}</span>'
        "</div>"
    )


def fmt_derivative(metric: dict[str, Any] | None, unit: str) -> str:
    if not metric:
        return '<span class="muted">缺失</span>'
    velocity = metric["velocity"]
    acceleration = metric["acceleration"]
    signal = metric["signal"]
    cls = "pos" if velocity > 0 else "neg" if velocity < 0 else "flat"
    accel_cls = "pos" if acceleration > 0 else "neg" if acceleration < 0 else "flat"
    signal_cls = "turn-up" if signal in {"转上", "下行减速"} else "turn-down" if signal in {"转下", "上行减速"} else "neutral"
    unit_label = "bp/d" if unit == "bp" else "%/d"
    accel_unit = "bp/d^2" if unit == "bp" else "%/d^2"
    return (
        '<div class="deriv-cell">'
        f'<div>D1 <span class="{cls}">{velocity:+.3f}{unit_label}</span></div>'
        f'<div>D2 <span class="{accel_cls}">{acceleration:+.4f}{accel_unit}</span></div>'
        f'<div><span class="tag {signal_cls}">{escape(signal)}</span></div>'
        "</div>"
    )


def render_html(snapshot: dict[str, Any]) -> str:
    countries = snapshot["countries"]
    rankings = snapshot["volatility_rankings"]
    second_order = snapshot["second_order_monitor"]
    ohlc_payload = {
        row["key"]: {
            "country": row["country"],
            "group": row["group"],
            "label": row["label"],
            "unit": row["unit"],
            "chartType": row.get("chart_type", "ohlc"),
            "ohlc": row.get("ohlc", []),
            "curve": row.get("curve"),
        }
        for row in second_order
    }
    ohlc_json = json.dumps(ohlc_payload, ensure_ascii=False).replace("</", "<\\/")
    generated = escape(snapshot["generated_at"])
    html = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Global Rates FX Equity Dashboard</title>",
        "<style>",
        CSS,
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        '<section class="topbar">',
        "<div>",
        "<h1>中美日德俄韩市场监控</h1>",
        f'<p class="muted">生成时间：{generated}</p>',
        "</div>",
        '<a class="button" href="latest_market_snapshot.json">JSON</a>',
        "</section>",
    ]

    html.extend(['<section class="panel volatility-panel">', "<h2>波动率排名</h2>", '<div class="ranking-grid">'])
    ranking_titles = {"bond": "债市波动率排名", "equity": "股指波动率排名", "fx": "汇率波动率排名"}
    for key in ["bond", "equity", "fx"]:
        rows = rankings.get(key, [])
        html.append('<div class="ranking-block">')
        html.append(f'<h3>{escape(ranking_titles[key])}</h3>')
        html.append('<div class="rank-row rank-head"><span>#</span><span>国家</span><span>7D</span><span>30D</span></div>')
        for row in rows:
            unit = row["unit"]
            windows = row["windows"]
            html.append(
                '<div class="rank-row">'
                f'<span>{row["rank"]}</span>'
                f'<strong>{escape(row["country"])}</strong>'
                f'<span>{escape(fmt_volatility_value(windows.get("7D"), unit))}</span>'
                f'<span>{escape(fmt_volatility_value(windows.get("30D"), unit))}</span>'
                "</div>"
            )
        html.append("</div>")
    html.extend(["</div></section>"])

    html.extend(['<section class="panel">', "<h2>一阶/二阶监控</h2>", '<div class="math-note">'])
    html.append("D1 是窗口速度；D2 是速度变化率。债券曲线使用 10Y-2Y，便于观察长短端价差变化速度。")
    html.extend(['</div>', '<div class="table-wrap">', '<table class="derivative-table">'])
    html.append("<thead><tr><th>国家</th><th>类型</th><th>标的</th><th>1D</th><th>7D</th><th>30D</th></tr></thead><tbody>")
    for row in second_order:
        html.append(
            f'<tr class="derivative-row" data-ohlc-key="{escape(row["key"])}" title="点击查看日线 OHLC">'
            f'<th>{escape(row["country"])}</th>'
            f'<td>{escape(row["group"])}</td>'
            f'<td>{escape(row["label"])}</td>'
            f'<td>{fmt_derivative(row["metrics"].get("1D"), row["unit"])}</td>'
            f'<td>{fmt_derivative(row["metrics"].get("7D"), row["unit"])}</td>'
            f'<td>{fmt_derivative(row["metrics"].get("30D"), row["unit"])}</td>'
            "</tr>"
        )
    html.extend(["</tbody></table></div></section>"])

    html.extend(
        [
            '<section class="panel ohlc-panel" id="ohlc-panel">',
            "<h2>日线 OHLC 可视化</h2>",
            '<div class="ohlc-head" id="ohlc-head">点击上方一阶/二阶监控中的任意一行查看日线图；鼠标放在单日上显示 OHLC。</div>',
            '<div class="chart-shell">',
            '<svg id="ohlc-chart" viewBox="0 0 980 360" role="img" aria-label="日线 OHLC 图"></svg>',
            '<div class="chart-tooltip" id="ohlc-tooltip"></div>',
            "</div>",
            "</section>",
        ]
    )

    html.extend(['<section class="panel">', "<h2>国家面板</h2>", '<div class="table-wrap">', '<table class="market-table">'])
    html.append(
        "<thead><tr><th>国家</th><th>2Y</th><th>2Y 1D/7D/14D/30D</th><th>10Y</th><th>10Y 1D/7D/14D/30D</th>"
        "<th>股指</th><th>股指 1D/7D/14D/30D</th><th>汇率</th><th>汇率 1D/7D/14D/30D</th></tr></thead><tbody>"
    )
    for row in countries:
        html.append("<tr>")
        html.append(f'<th class="country">{escape(row["country"])}<span>{escape(row["ccy"])}</span></th>')
        for field, unit, digits in [("bond_2y", "bp", 3), ("bond_10y", "bp", 3), ("equity", "pct", 2), ("fx", "pct", 5)]:
            cell = row[field]
            summary = cell["summary"]
            latest = summary.get("latest")
            stale = '<span class="tag warn">旧</span>' if summary.get("stale") else ""
            html.append(
                f'<td><div class="cell-label">{escape(cell["label"])}</div>'
                f'<div>{escape(fmt_value(latest, digits))} {stale}</div>'
                f'<div class="date">{escape(summary.get("date") or "")}</div>'
                f'{fmt_asset_volatility(summary, unit)}</td>'
            )
            html.append(
                "<td class=\"change-stack\">"
                f'{fmt_change(summary, "chg_1d", unit)}'
                f'{fmt_change(summary, "chg_7d", unit)}'
                f'{fmt_change(summary, "chg_14d", unit)}'
                f'{fmt_change(summary, "chg_30d", unit)}'
                "</td>"
            )
        html.append("</tr>")
    html.extend(["</tbody></table></div></section>"])

    html.extend(['<section class="panel">', "<h2>三币种资金流向</h2>", '<div class="flow-grid">'])
    for section in snapshot["fx_flows"]:
        html.append('<div class="flow-block">')
        html.append(f'<h3>{escape(section["name"])}</h3>')
        for period in section["periods"]:
            html.append('<div class="flow-row">')
            html.append(f'<div class="period">{escape(period["period"])}</div>')
            result = period["result"]
            if result and result["best_route"]:
                best = result["best_route"]
                ranking = " > ".join(result["ranking"])
                html.append(
                    f'<div><strong>{escape(best["label"])}</strong> '
                    f'<span class="pos">{best["score"]:+.4f}</span>'
                    f'<div class="muted">强弱：{escape(ranking)}</div></div>'
                )
            else:
                html.append(f'<div class="muted">缺少：{escape(", ".join(period["missing"]))}</div>')
            html.append("</div>")
        html.append("</div>")
    html.extend(["</div></section>"])

    html.extend(['<section class="panel">', "<h2>数据状态</h2>", '<div class="table-wrap">', '<table class="status-table">'])
    html.append("<thead><tr><th>Key</th><th>名称</th><th>来源</th><th>符号</th><th>最新日期</th><th>最新值</th><th>状态</th></tr></thead><tbody>")
    for item in snapshot["series_status"]:
        status = '<span class="tag warn">旧/缺</span>' if item["stale"] else '<span class="tag ok">OK</span>'
        html.append(
            "<tr>"
            f'<td>{escape(item["key"])}</td><td>{escape(item["label"])}</td><td>{escape(item["source"])}</td>'
            f'<td>{escape(item["symbol"])}</td><td>{escape(item["latest_date"])}</td>'
            f'<td>{escape(fmt_value(item["latest"], 5))}</td><td>{status}</td></tr>'
        )
    html.extend(["</tbody></table></div></section>"])

    html.extend(['<section class="notes">'])
    for note in snapshot["notes"]:
        html.append(f"<p>{escape(note)}</p>")
    html.extend(
        [
            "</section>",
            f'<script id="ohlc-data" type="application/json">{ohlc_json}</script>',
            "<script>",
            JS,
            "</script>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )
    return "\n".join(html)


CSS = """
:root {
  color-scheme: light;
  --bg: #f6f7f8;
  --panel: #ffffff;
  --ink: #1d2329;
  --muted: #66717d;
  --line: #d9dee5;
  --pos: #b42318;
  --neg: #087443;
  --blue: #2457a6;
  --amber: #9a5b00;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", Arial, sans-serif;
}
main { max-width: 1480px; margin: 0 auto; padding: 24px; }
.topbar { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
h1 { margin: 0 0 4px; font-size: 28px; letter-spacing: 0; }
h2 { margin: 0 0 14px; font-size: 18px; letter-spacing: 0; }
h3 { margin: 0 0 10px; font-size: 15px; letter-spacing: 0; }
.muted, .date { color: var(--muted); }
.date { font-size: 12px; margin-top: 2px; }
.button { border: 1px solid var(--line); color: var(--ink); text-decoration: none; padding: 8px 12px; border-radius: 6px; background: #fff; }
.panel, .flow-block { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
.panel { padding: 16px; margin-top: 14px; }
.ranking-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
.ranking-block + .ranking-block { border-left: 1px solid var(--line); padding-left: 18px; }
.rank-row { display: grid; grid-template-columns: 28px minmax(58px, 1fr) minmax(76px, auto) minmax(76px, auto); gap: 8px; align-items: baseline; padding: 5px 0; font-variant-numeric: tabular-nums; }
.rank-row span:nth-child(n+3) { text-align: right; }
.rank-head { color: var(--muted); font-size: 12px; font-weight: 650; border-bottom: 1px solid var(--line); margin-bottom: 4px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: right; vertical-align: top; white-space: nowrap; }
thead th { color: var(--muted); font-size: 12px; font-weight: 650; background: #f9fafb; }
th:first-child, td:first-child { text-align: left; }
.country span { display: block; color: var(--muted); font-weight: 500; font-size: 12px; }
.cell-label { color: var(--muted); font-size: 12px; }
.asset-vol { display: grid; gap: 1px; margin-top: 6px; color: var(--muted); font-size: 11px; line-height: 1.35; font-variant-numeric: tabular-nums; }
.change-stack { display: grid; grid-template-columns: repeat(4, minmax(58px, 1fr)); gap: 6px; align-items: start; }
.pos { color: var(--pos); font-variant-numeric: tabular-nums; }
.neg { color: var(--neg); font-variant-numeric: tabular-nums; }
.flat { color: var(--muted); font-variant-numeric: tabular-nums; }
.tag { display: inline-block; padding: 1px 6px; border-radius: 999px; font-size: 11px; font-weight: 650; }
.tag.warn { color: #7a4100; background: #fff3d8; }
.tag.ok { color: #075e3f; background: #dcfce7; }
.tag.turn-up { color: #075e3f; background: #dcfce7; }
.tag.turn-down { color: #7a4100; background: #fff3d8; }
.tag.neutral { color: #475569; background: #e9eef5; }
.math-note { color: var(--muted); font-size: 13px; margin: -4px 0 12px; }
.derivative-table th, .derivative-table td { text-align: left; }
.derivative-table td:nth-child(n+4), .derivative-table th:nth-child(n+4) { text-align: right; }
.derivative-row { cursor: pointer; }
.derivative-row:hover { background: #f3f6fa; }
.derivative-row.selected { background: #eaf2ff; }
.deriv-cell { display: grid; gap: 2px; font-size: 12px; line-height: 1.35; min-width: 134px; }
.deriv-cell .tag { margin-top: 2px; }
.ohlc-panel { scroll-margin-top: 18px; }
.ohlc-head { color: var(--muted); margin: -4px 0 12px; font-size: 13px; }
.chart-shell { position: relative; border: 1px solid var(--line); border-radius: 8px; background: #fff; overflow: hidden; }
#ohlc-chart { display: block; width: 100%; height: min(52vw, 420px); min-height: 320px; }
.chart-tooltip {
  position: absolute;
  display: none;
  pointer-events: none;
  z-index: 5;
  min-width: 164px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: rgba(255,255,255,0.96);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
  padding: 8px 10px;
  color: var(--ink);
  font-size: 12px;
  line-height: 1.45;
  font-variant-numeric: tabular-nums;
}
.chart-tooltip strong { display: block; margin-bottom: 4px; }
.flow-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.flow-block { padding: 12px; }
.flow-row { display: grid; grid-template-columns: 52px 1fr; gap: 10px; border-top: 1px solid var(--line); padding: 10px 0 0; margin-top: 10px; }
.period { color: var(--blue); font-weight: 700; }
.status-table th, .status-table td { text-align: left; }
.notes { color: var(--muted); font-size: 13px; margin: 14px 0 0; }
.notes p { margin: 4px 0; }
@media (max-width: 900px) {
  main { padding: 14px; }
  .topbar { align-items: flex-start; flex-direction: column; }
  .ranking-grid, .flow-grid { grid-template-columns: 1fr; }
  .ranking-block + .ranking-block { border-left: 0; border-top: 1px solid var(--line); padding-left: 0; padding-top: 12px; }
}
"""


JS = """
(() => {
  const raw = document.getElementById("ohlc-data")?.textContent || "{}";
  const ohlcData = JSON.parse(raw);
  const rows = Array.from(document.querySelectorAll(".derivative-row"));
  const head = document.getElementById("ohlc-head");
  const svg = document.getElementById("ohlc-chart");
  const tooltip = document.getElementById("ohlc-tooltip");
  const panel = document.getElementById("ohlc-panel");

  const fmt = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "缺失";
    const abs = Math.abs(Number(value));
    const digits = abs >= 1000 ? 2 : abs >= 10 ? 4 : 5;
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits
    });
  };

  const esc = (value) => String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

  const yTicks = (min, max, count = 5) => {
    if (min === max) return [min];
    const ticks = [];
    for (let i = 0; i < count; i += 1) {
      ticks.push(min + (max - min) * i / (count - 1));
    }
    return ticks;
  };

  const renderChart = (item) => {
    const bars = item.ohlc || [];
    const width = 980;
    const height = 360;
    const margin = { left: 64, right: 22, top: 22, bottom: 38 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;
    if (!bars.length) {
      svg.innerHTML = `<text x="490" y="180" text-anchor="middle" fill="#66717d">没有 OHLC 数据</text>`;
      return;
    }
    const highs = bars.map((bar) => Number(bar.high));
    const lows = bars.map((bar) => Number(bar.low));
    let min = Math.min(...lows);
    let max = Math.max(...highs);
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const pad = (max - min) * 0.08;
    min -= pad;
    max += pad;
    const xStep = innerW / Math.max(1, bars.length - 1);
    const candleW = Math.max(2, Math.min(9, xStep * 0.56));
    const y = (value) => margin.top + (max - Number(value)) / (max - min) * innerH;
    const x = (index) => margin.left + index * xStep;

    const grid = yTicks(min, max).map((tick) => {
      const yy = y(tick);
      return `<line x1="${margin.left}" x2="${width - margin.right}" y1="${yy}" y2="${yy}" stroke="#e5e9ef" />`
        + `<text x="${margin.left - 10}" y="${yy + 4}" text-anchor="end" fill="#66717d" font-size="11">${fmt(tick)}</text>`;
    }).join("");

    const dateTicks = [];
    const tickCount = Math.min(6, bars.length);
    for (let i = 0; i < tickCount; i += 1) {
      const index = Math.round(i * (bars.length - 1) / Math.max(1, tickCount - 1));
      const xx = x(index);
      dateTicks.push(`<text x="${xx}" y="${height - 13}" text-anchor="middle" fill="#66717d" font-size="11">${esc(bars[index].date.slice(5))}</text>`);
    }

    const candles = bars.map((bar, index) => {
      const xx = x(index);
      const open = Number(bar.open);
      const close = Number(bar.close);
      const high = Number(bar.high);
      const low = Number(bar.low);
      const up = close >= open;
      const color = up ? "#b42318" : "#087443";
      const bodyTop = y(Math.max(open, close));
      const bodyBottom = y(Math.min(open, close));
      const bodyH = Math.max(1.2, bodyBottom - bodyTop);
      const hitW = Math.max(8, xStep);
      return `<g class="candle" data-index="${index}">`
        + `<line x1="${xx}" x2="${xx}" y1="${y(high)}" y2="${y(low)}" stroke="${color}" stroke-width="1.4" />`
        + `<rect x="${xx - candleW / 2}" y="${bodyTop}" width="${candleW}" height="${bodyH}" fill="${up ? color : "#ffffff"}" stroke="${color}" stroke-width="1.3" />`
        + `<rect class="hit" x="${xx - hitW / 2}" y="${margin.top}" width="${hitW}" height="${innerH}" fill="transparent" />`
        + `</g>`;
    }).join("");

    svg.innerHTML = `<rect width="${width}" height="${height}" fill="#fff" />`
      + `<line x1="${margin.left}" x2="${margin.left}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#cbd3dd" />`
      + `<line x1="${margin.left}" x2="${width - margin.right}" y1="${height - margin.bottom}" y2="${height - margin.bottom}" stroke="#cbd3dd" />`
      + grid
      + dateTicks.join("")
      + candles;

    Array.from(svg.querySelectorAll(".candle")).forEach((node) => {
      const bar = bars[Number(node.dataset.index)];
      node.addEventListener("mousemove", (event) => {
        const bounds = panel.getBoundingClientRect();
        tooltip.style.display = "block";
        tooltip.style.left = `${Math.min(bounds.width - 190, Math.max(8, event.clientX - bounds.left + 14))}px`;
        tooltip.style.top = `${Math.max(8, event.clientY - bounds.top - 70)}px`;
        tooltip.innerHTML = `<strong>${esc(bar.date)}</strong>`
          + `<div>Open: ${fmt(bar.open)}</div>`
          + `<div>High: ${fmt(bar.high)}</div>`
          + `<div>Low: ${fmt(bar.low)}</div>`
          + `<div>Close: ${fmt(bar.close)}</div>`;
      });
      node.addEventListener("mouseleave", () => {
        tooltip.style.display = "none";
      });
    });
  };

  const renderBondCurveChart = (item) => {
    const curve = item.curve || {};
    const bars = curve.rows || [];
    const width = 980;
    const height = 360;
    const margin = { left: 64, right: 22, top: 34, bottom: 38 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;
    if (!bars.length) {
      svg.innerHTML = `<text x="490" y="180" text-anchor="middle" fill="#66717d">没有 2Y/10Y 曲线数据</text>`;
      return;
    }

    const values = bars.flatMap((bar) => [Number(bar.bond_2y), Number(bar.bond_10y)]);
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const pad = (max - min) * 0.10;
    min -= pad;
    max += pad;

    const xStep = innerW / Math.max(1, bars.length - 1);
    const y = (value) => margin.top + (max - Number(value)) / (max - min) * innerH;
    const x = (index) => margin.left + index * xStep;
    const linePath = (field) => bars.map((bar, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(bar[field]).toFixed(2)}`).join(" ");

    const grid = yTicks(min, max).map((tick) => {
      const yy = y(tick);
      return `<line x1="${margin.left}" x2="${width - margin.right}" y1="${yy}" y2="${yy}" stroke="#e5e9ef" />`
        + `<text x="${margin.left - 10}" y="${yy + 4}" text-anchor="end" fill="#66717d" font-size="11">${fmt(tick)}%</text>`;
    }).join("");

    const dateTicks = [];
    const tickCount = Math.min(6, bars.length);
    for (let i = 0; i < tickCount; i += 1) {
      const index = Math.round(i * (bars.length - 1) / Math.max(1, tickCount - 1));
      const xx = x(index);
      dateTicks.push(`<text x="${xx}" y="${height - 13}" text-anchor="middle" fill="#66717d" font-size="11">${esc(bars[index].date.slice(5))}</text>`);
    }

    const bands = bars.slice(0, -1).map((bar, index) => {
      const next = bars[index + 1];
      const positive = (Number(bar.spread_bp) + Number(next.spread_bp)) / 2 >= 0;
      const fill = positive ? "rgba(8, 116, 67, 0.16)" : "rgba(180, 35, 24, 0.16)";
      const cls = positive ? "curve-positive-band" : "curve-negative-band";
      const points = [
        [x(index), y(bar.bond_10y)],
        [x(index + 1), y(next.bond_10y)],
        [x(index + 1), y(next.bond_2y)],
        [x(index), y(bar.bond_2y)]
      ].map(([px, py]) => `${px.toFixed(2)},${py.toFixed(2)}`).join(" ");
      return `<polygon class="${cls}" points="${points}" fill="${fill}" />`;
    }).join("");

    const hitW = Math.max(8, xStep);
    const hits = bars.map((bar, index) => (
      `<rect class="curve-hit" data-index="${index}" x="${x(index) - hitW / 2}" y="${margin.top}" width="${hitW}" height="${innerH}" fill="transparent" />`
    )).join("");

    svg.innerHTML = `<rect width="${width}" height="${height}" fill="#fff" />`
      + `<line x1="${margin.left}" x2="${margin.left}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#cbd3dd" />`
      + `<line x1="${margin.left}" x2="${width - margin.right}" y1="${height - margin.bottom}" y2="${height - margin.bottom}" stroke="#cbd3dd" />`
      + grid
      + dateTicks.join("")
      + bands
      + `<path d="${linePath("bond_10y")}" fill="none" stroke="#2457a6" stroke-width="2.2" />`
      + `<path d="${linePath("bond_2y")}" fill="none" stroke="#9a5b00" stroke-width="2.2" />`
      + `<text x="${margin.left}" y="18" fill="#2457a6" font-size="12" font-weight="700">10Y</text>`
      + `<text x="${margin.left + 42}" y="18" fill="#9a5b00" font-size="12" font-weight="700">2Y</text>`
      + `<text x="${margin.left + 84}" y="18" fill="#087443" font-size="12">10Y > 2Y</text>`
      + `<text x="${margin.left + 174}" y="18" fill="#b42318" font-size="12">10Y < 2Y</text>`
      + hits;

    Array.from(svg.querySelectorAll(".curve-hit")).forEach((node) => {
      const bar = bars[Number(node.dataset.index)];
      node.addEventListener("mousemove", (event) => {
        const bounds = panel.getBoundingClientRect();
        tooltip.style.display = "block";
        tooltip.style.left = `${Math.min(bounds.width - 218, Math.max(8, event.clientX - bounds.left + 14))}px`;
        tooltip.style.top = `${Math.max(8, event.clientY - bounds.top - 82)}px`;
        const spread = Number(bar.spread_bp);
        const spreadText = `${spread >= 0 ? "+" : ""}${fmt(spread)}bp`;
        tooltip.innerHTML = `<strong>${esc(bar.date)}</strong>`
          + `<div>${esc(curve.bond_10y_label || "10Y")}: ${fmt(bar.bond_10y)}%</div>`
          + `<div>${esc(curve.bond_2y_label || "2Y")}: ${fmt(bar.bond_2y)}%</div>`
          + `<div>Spread: ${spreadText}</div>`
          + `<div>${bar.positive ? "10Y > 2Y，正斜率" : "10Y < 2Y，倒挂"}</div>`;
      });
      node.addEventListener("mouseleave", () => {
        tooltip.style.display = "none";
      });
    });
  };

  const render = (key) => {
    const item = ohlcData[key];
    if (!item) return;
    rows.forEach((row) => row.classList.toggle("selected", row.dataset.ohlcKey === key));
    if (item.chartType === "bond_curve") {
      const count = item.curve?.rows?.length || 0;
      head.textContent = `${item.country} / 债券曲线：2Y 与 10Y 最近 ${count} 条日线 close；绿色为 10Y > 2Y，红色为 10Y < 2Y。`;
      renderBondCurveChart(item);
    } else {
      head.textContent = `${item.country} / ${item.group} / ${item.label}：最近 ${item.ohlc.length} 条日线，鼠标悬停显示 OHLC`;
      renderChart(item);
    }
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  rows.forEach((row) => {
    row.addEventListener("click", () => render(row.dataset.ohlcKey));
  });
})();
"""


def main() -> int:
    args = parse_args()
    fetch_records = fetch_all(args) if args.fetch else []
    snapshot = build_snapshot(fetch_records)
    DASHBOARD.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_JSON.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    HTML_OUT.write_text(render_html(snapshot), encoding="utf-8")
    print(f"wrote {HTML_OUT}")
    print(f"wrote {SNAPSHOT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
