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
from policy_news import build_policy_news_snapshot


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
    SeriesSpec("US_1Y", "美国1年国债", "bond", "wscn", "US1YR.OTC", "US_1Y.csv", "US1YR_OTC_1D_ohlc.csv"),
    SeriesSpec("US_2Y", "美国2年国债", "bond", "wscn", "US2YR.OTC", "US_2Y.csv", "US2YR_OTC_1D_ohlc.csv"),
    SeriesSpec("US_10Y", "美国10年国债", "bond", "wscn", "US10YR.OTC", "US_10Y.csv", "US10YR_OTC_1D_ohlc.csv"),
    SeriesSpec("CN_1Y", "中国1年国债", "bond", "wscn", "CN1YR.OTC", "CN_1Y.csv", "CN1YR_OTC_1D_ohlc.csv"),
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
        SeriesSpec("JP_1Y", "日本1年国债", "bond", "investing", "JP1YT=XX", "JP_1Y.csv", "JP1YR_INVESTING_1D_ohlc.csv"),
        InvestingSpec("JP1Y", "23892", "JP1YT=XX", "japan-1-year-bond-yield-historical-data", "Japan 1-Year Bond Yield Historical Data", "JP1YR_INVESTING_1D_ohlc.csv"),
    ),
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
    SeriesSpec("JP_EQUITY_YAHOO", "日经225", "equity", "yahoo", "^N225", "JP_EQUITY_YAHOO.csv", "NIKKEI225_YAHOO_1D_ohlc.csv"),
    SeriesSpec("DE_EQUITY", "德国DAX", "equity", "yahoo", "^GDAXI", "DE_EQUITY.csv", None),
    SeriesSpec("KR_EQUITY", "韩国KOSPI", "equity", "yahoo", "^KS11", "KR_EQUITY.csv", None),
    SeriesSpec("KRWCNY", "韩元/人民币", "fx", "yahoo", "KRWCNY=X", "KRWCNY.csv", None),
    SeriesSpec("USDKRW", "美元/韩元", "fx", "yahoo", "USDKRW=X", "USDKRW.csv", None),
    SeriesSpec("RUBCNY_YAHOO", "卢布/人民币", "fx", "yahoo", "RUBCNY=X", "RUBCNY_YAHOO.csv", None),
    SeriesSpec("RUBJPY_YAHOO", "卢布/日元", "fx", "yahoo", "RUBJPY=X", "RUBJPY_YAHOO.csv", None),
    SeriesSpec("USDRUB_YAHOO", "美元/卢布", "fx", "yahoo", "USDRUB=X", "USDRUB_YAHOO.csv", None),
]

NIKKEI_SPECS = [
    SeriesSpec("JP_EQUITY", "日经225", "equity", "nikkei", "nikkei_stock_average_daily_en.csv", "JP_EQUITY.csv", None),
]

COUNTRIES = [
    {"code": "US", "name": "美国", "ccy": "USD", "bond_1y": "US_1Y", "bond_2y": "US_2Y", "bond_10y": "US_10Y", "equity": "US_EQUITY", "fx": "USDCNY"},
    {"code": "CN", "name": "中国", "ccy": "CNY", "bond_1y": "CN_1Y", "bond_2y": "CN_2Y", "bond_10y": "CN_10Y", "equity": "CN_EQUITY", "fx": "CNY_BASE"},
    {"code": "JP", "name": "日本", "ccy": "JPY", "bond_1y": "JP_1Y", "bond_2y": "JP_2Y", "bond_10y": "JP_10Y", "equity": "JP_EQUITY", "fx": "JPYCNY"},
    {"code": "DE", "name": "德国", "ccy": "EUR", "bond_2y": "DE_2Y", "bond_10y": "DE_10Y", "equity": "DE_EQUITY", "fx": "EURCNY"},
    {"code": "RU", "name": "俄罗斯", "ccy": "RUB", "bond_2y": "RU_2Y", "bond_10y": "RU_10Y", "equity": "RU_EQUITY", "fx": "RUBCNY"},
    {"code": "KR", "name": "韩国", "ccy": "KRW", "bond_2y": "KR_2Y", "bond_10y": "KR_10Y", "equity": "KR_EQUITY", "fx": "KRWCNY"},
]

CURRENCY_NAMES = {
    "CNY": "人民币",
    "USD": "美元",
    "JPY": "日元",
    "EUR": "欧元",
    "RUB": "俄罗斯卢布",
    "KRW": "韩元",
}

FX_CNY_SERIES = {
    "CNY": "CNY_BASE",
    "USD": "USDCNY",
    "JPY": "JPYCNY",
    "EUR": "EURCNY",
    "RUB": "RUBCNY",
    "KRW": "KRWCNY",
}

FX_DETAIL_BASES = ("CNY", "USD", "JPY")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", dest="fetch", action="store_true", default=True, help="Fetch latest WSCN/Yahoo data before rendering.")
    parser.add_argument("--no-fetch", dest="fetch", action="store_false", help="Use cached/local CSV files only.")
    parser.add_argument("--lookback-days", type=int, default=540, help="Yahoo fetch lookback window.")
    parser.add_argument("--wscn-count", type=int, default=1800, help="WSCN rows per series.")
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

    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        open_px = value_at(quote_data.get("open"), index)
        high_px = value_at(quote_data.get("high"), index)
        low_px = value_at(quote_data.get("low"), index)
        close_px = value_at(quote_data.get("close"), index)
        volume = value_at(quote_data.get("volume"), index)
        if close_px is None and index == len(timestamps) - 1:
            close_px = meta.get("regularMarketPrice")
            open_px = open_px if open_px is not None else close_px
            high_px = high_px if high_px is not None else close_px
            low_px = low_px if low_px is not None else close_px
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


def fetch_nikkei_ohlc(symbol: str) -> list[dict[str, Any]]:
    url = f"https://indexes.nikkei.co.jp/nkave/historical/{quote(symbol, safe='')}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"})
    with urlopen(request, timeout=30) as response:
        text = response.read().decode("cp932")

    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(text.splitlines()):
        try:
            parsed_date = datetime.strptime(row["Date of Data"], "%Y/%m/%d").date()
            close = float(row["Close"].replace(",", ""))
            open_px = float(row["Open"].replace(",", ""))
            high = float(row["High"].replace(",", ""))
            low = float(row["Low"].replace(",", ""))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        timestamp = int(datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc).timestamp())
        rows.append(
            {
                "date": parsed_date.isoformat(),
                "timestamp": timestamp,
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": "",
                "source_symbol": symbol,
                "source": "Nikkei Indexes official daily CSV",
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

    for spec in NIKKEI_SPECS:
        path = DASHBOARD_DATA / spec.cache_file
        record = {"key": spec.key, "source": spec.source, "symbol": spec.symbol, "status": "pending", "file": str(path), "error": ""}
        try:
            rows = fetch_nikkei_ohlc(spec.symbol)
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
    specs = {spec.key: spec for spec in [*WSCN_SPECS, *YAHOO_SPECS, *NIKKEI_SPECS, *investing_series_specs]}
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

    rubcny_direct = series.get("RUBCNY_YAHOO", [])
    rubcny_derived = derived_ratio("RUBCNY", usdcny, usdrub, "USDCNY / USDRUB")
    if enough_recent_history(rubcny_direct, 30):
        specs["RUBCNY"] = SeriesSpec("RUBCNY", "卢布/人民币", "fx", "yahoo", "RUBCNY=X", "RUBCNY.csv")
        series["RUBCNY"] = rubcny_direct
    else:
        specs["RUBCNY"] = SeriesSpec("RUBCNY", "卢布/人民币", "fx", "derived", "USDCNY/USDRUB", "RUBCNY.csv")
        series["RUBCNY"] = rubcny_derived

    rubjpy_direct = series.get("RUBJPY_YAHOO", [])
    rubjpy_derived = derived_ratio("RUBJPY", usd_jpy, usdrub, "USDJPY / USDRUB")
    if enough_recent_history(rubjpy_direct, 30):
        specs["RUBJPY"] = SeriesSpec("RUBJPY", "卢布/日元", "fx", "yahoo", "RUBJPY=X", "RUBJPY.csv")
        series["RUBJPY"] = rubjpy_direct
    else:
        specs["RUBJPY"] = SeriesSpec("RUBJPY", "卢布/日元", "fx", "derived", "USDJPY/USDRUB", "RUBJPY.csv")
        series["RUBJPY"] = rubjpy_derived

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


def compare_on_latest_common_date(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any] | None:
    left_latest = latest_row(left)
    right_latest = latest_row(right)
    if not left_latest or not right_latest:
        return None
    target = min(left_latest["date"], right_latest["date"])
    left_row = at_or_before(left, target)
    right_row = at_or_before(right, target)
    if not left_row or not right_row or right_row["close"] == 0:
        return None
    diff = left_row["close"] - right_row["close"]
    return {
        "date": target.isoformat(),
        "left": left_row["close"],
        "right": right_row["close"],
        "abs_diff": diff,
        "pct_diff": diff / right_row["close"] * 100,
    }


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
            *([("债券", country["bond_1y"], "bp")] if country.get("bond_1y") else []),
            ("债券", country["bond_2y"], "bp"),
            ("债券", country["bond_10y"], "bp"),
            ("债券曲线", f"{country['code']}_10Y2Y", "bp"),
        ]
        for group, key, unit in instruments:
            spec = specs.get(key)
            data_rows = series.get(key, [])
            metrics = {f"{days}D": derivative_metrics(data_rows, days, unit=unit) for days in windows}
            item = {
                "country": country["name"],
                "code": country["code"],
                "group": group,
                "key": key,
                "label": spec.label if spec else key,
                "unit": unit,
                "metrics": metrics,
                "ohlc": recent_ohlc_rows(data_rows, limit=360),
                "chart_type": "ohlc",
            }
            if group != "债券曲线":
                item["summary"] = series_summary(key, data_rows, unit, stale_days=spec.stale_days if spec else 7)
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
                        limit=360,
                    ),
                }
            rows.append(item)
    return rows


def recent_ohlc_rows(rows: list[dict[str, Any]], limit: int = 90) -> list[dict[str, Any]]:
    out = []
    start = max(0, len(rows) - limit)
    for index in range(start, len(rows)):
        row = rows[index]
        item = {
            "date": row["date"].isoformat(),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
        }
        if index > 0:
            prev_close = rows[index - 1].get("close")
            close = row.get("close")
            if (
                prev_close is not None
                and close is not None
                and math.isfinite(float(prev_close))
                and math.isfinite(float(close))
                and float(prev_close) != 0
            ):
                item["prev_close"] = prev_close
                item["change_pct"] = (float(close) - float(prev_close)) / float(prev_close) * 100
        out.append(item)
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
                    "code": country["code"],
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


def fx_range(rows: list[dict[str, Any]], days: int) -> dict[str, Any] | None:
    latest = latest_row(rows)
    if not latest:
        return None
    cutoff = latest["date"] - timedelta(days=days)
    window = [row for row in rows if cutoff <= row["date"] <= latest["date"]]
    if not window:
        return None
    values = [row["close"] for row in window]
    return {
        "low": min(values),
        "high": max(values),
        "start_date": window[0]["date"].isoformat(),
        "end_date": latest["date"].isoformat(),
    }


def build_fx_cross_details(series: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    for country in COUNTRIES:
        target_ccy = country["ccy"]
        target_key = FX_CNY_SERIES.get(target_ccy, "")
        target_rows = series.get(target_key, [])
        rows = []
        for base_ccy in FX_DETAIL_BASES:
            if base_ccy == target_ccy:
                continue
            base_key = FX_CNY_SERIES.get(base_ccy, "")
            base_rows = series.get(base_key, [])
            cross_rows = derived_ratio(f"{base_ccy}{target_ccy}", base_rows, target_rows, f"{base_key} / {target_key}")
            latest = latest_row(cross_rows)
            if not latest:
                continue
            previous = prior_row_before(cross_rows, latest["date"])
            move = change(cross_rows, None, unit="pct")
            move_7d = change(cross_rows, 7, unit="pct")
            move_30d = change(cross_rows, 30, unit="pct")
            rows.append(
                {
                    "pair": f"{base_ccy}/{target_ccy}",
                    "name": f"{CURRENCY_NAMES.get(base_ccy, base_ccy)}/{CURRENCY_NAMES.get(target_ccy, target_ccy)}",
                    "latest": latest["close"],
                    "latest_date": latest["date"].isoformat(),
                    "change": latest["close"] - previous["close"] if previous else None,
                    "pct_change": move["value"] if move else None,
                    "base_date": move["base_date"] if move else "",
                    "pct_change_7d": move_7d["value"] if move_7d else None,
                    "pct_change_30d": move_30d["value"] if move_30d else None,
                    "change_7d_dates": {
                        "base_date": move_7d["base_date"],
                        "latest_date": move_7d["latest_date"],
                    }
                    if move_7d
                    else None,
                    "change_30d_dates": {
                        "base_date": move_30d["base_date"],
                        "latest_date": move_30d["latest_date"],
                    }
                    if move_30d
                    else None,
                    "range_7d": fx_range(cross_rows, 7),
                    "range_30d": fx_range(cross_rows, 30),
                    "source": f"{base_key}/{target_key}",
                }
            )
        details[country["code"]] = {
            "country": country["name"],
            "target_ccy": target_ccy,
            "rows": rows,
        }
    return details


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


def build_snapshot(fetch_records: list[dict[str, str]], *, fetch_policy_news: bool = True) -> dict[str, Any]:
    series, specs = load_all_series()
    countries = build_country_rows(series, specs)
    snapshot = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "policy_news": build_policy_news_snapshot(fetch_news=fetch_policy_news),
        "countries": countries,
        "asset_class_vol": asset_class_vol(countries),
        "volatility_rankings": volatility_rankings(countries),
        "fx_rank_details": build_fx_cross_details(series),
        "second_order_monitor": build_second_order_monitor(series, specs),
        "fx_flows": build_flow_sections(series),
        "hike_cycle_example": build_hike_cycle_example(series),
        "series_status": build_series_status(series, specs),
        "source_audit": build_source_audit(series, specs),
        "fetch_records": fetch_records,
        "notes": [
            "债券变化单位为 bp；股指和汇率变化单位为对数百分比。",
            "一阶速度 = 当前窗口变化 / 实际间隔天数；二阶加速度 = 当前一阶速度相对上一段同长度窗口的速度变化 / 平均间隔天数。",
            "7D/30D 波动率 = 对应窗口相邻交易观测的平均绝对日变化；债券单位 bp/日，股指和汇率单位 %/日。",
            f"三币种资金流向直接调用用户提供代码：{USER_FX_FLOW_CODE}",
            "derived = 本地公式而非外部供应商：CNY_BASE=1；债券曲线=10Y-2Y；CNYJPY=1/JPYCNY；RUB 交叉汇率优先使用具备历史深度的 Yahoo 直接报价，历史不足才用 USDCNY/USDRUB 或 USDJPY/USDRUB 派生并在 source_audit 里比对最新直接报价。",
            "WSCN 缺口优先用 Yahoo；日本/德国/俄罗斯/韩国债券因 WSCN 对应符号缺失或陈旧，使用 Investing 历史日线。",
            "政策新闻雷达只做加息、降息、维持利率相关文本筛选；抓取或 AI 分类不可用时退回本地规则解析。",
        ],
    }
    return snapshot


def row_on_or_after(rows: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    for row in rows:
        if row["date"] >= target:
            return row
    return None


def date_range_rows(rows: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [row for row in rows if start <= row["date"] <= end]


def extreme_row(rows: list[dict[str, Any]], start: date, end: date, field: str, mode: str) -> dict[str, Any] | None:
    window = date_range_rows(rows, start, end)
    if not window:
        return None
    if mode == "max":
        return max(window, key=lambda row: row[field])
    return min(window, key=lambda row: row[field])


def yield_leg(
    rows: list[dict[str, Any]],
    start: date,
    end: date,
    *,
    mode: str,
) -> dict[str, Any] | None:
    if mode == "low_high":
        start_row = extreme_row(rows, start, end, "low", "min")
        candidates = [row for row in date_range_rows(rows, start, end) if start_row and row["date"] >= start_row["date"]]
        end_row = max(candidates, key=lambda row: row["high"]) if candidates else None
        start_field = "low"
        end_field = "high"
    elif mode == "high_low":
        start_row = extreme_row(rows, start, end, "high", "max")
        candidates = [row for row in date_range_rows(rows, start, end) if start_row and row["date"] >= start_row["date"]]
        end_row = min(candidates, key=lambda row: row["low"]) if candidates else None
        start_field = "high"
        end_field = "low"
    else:
        start_row = row_on_or_after(rows, start)
        end_row = at_or_before(rows, end)
        start_field = "close"
        end_field = "close"
    if not start_row or not end_row:
        return None

    start_value = start_row[start_field]
    end_value = end_row[end_field]
    return {
        "start_date": start_row["date"].isoformat(),
        "end_date": end_row["date"].isoformat(),
        "start": start_value,
        "end": end_value,
        "pct": (end_value / start_value - 1) * 100 if start_value else None,
        "bp": (end_value - start_value) * 100,
    }


def covers_period(rows: list[dict[str, Any]], start: date, end: date) -> bool:
    return bool(rows and rows[0]["date"] <= start and rows[-1]["date"] >= end)


def long_history_rows(current_rows: list[dict[str, Any]], local_file: str, start: date, end: date) -> list[dict[str, Any]]:
    if covers_period(current_rows, start, end):
        return current_rows
    local_path = LOCAL_DATA / local_file
    if local_path.exists():
        local_rows = read_ohlc(local_path)
        if covers_period(local_rows, start, end):
            return local_rows
    return current_rows


def paired_yield_points(
    us2: list[dict[str, Any]],
    us10: list[dict[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row_10y in date_range_rows(us10, start, end):
        row_2y = at_or_before(us2, row_10y["date"])
        if not row_2y:
            continue
        points.append(
            {
                "date": row_10y["date"].isoformat(),
                "us2y": row_2y["close"],
                "us10y": row_10y["close"],
            }
        )
    return points


def single_yield_points(rows: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [
        {
            "date": row["date"].isoformat(),
            "value": row["close"],
        }
        for row in date_range_rows(rows, start, end)
    ]


def build_hike_cycle_example(series: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    start = date(2020, 7, 1)
    end = date(2022, 6, 14)
    us2 = long_history_rows(series.get("US_2Y", []), "US2YR_OTC_1D_ohlc.csv", start, end)
    us10 = long_history_rows(series.get("US_10Y", []), "US10YR_OTC_1D_ohlc.csv", start, end)
    base_2y = row_on_or_after(us2, start)
    base_10y = row_on_or_after(us10, start)
    points: list[dict[str, Any]] = []
    if base_2y and base_10y:
        for row_10y in date_range_rows(us10, start, end):
            row_2y = at_or_before(us2, row_10y["date"])
            if not row_2y:
                continue
            points.append(
                {
                    "date": row_10y["date"].isoformat(),
                    "us2y": row_2y["close"],
                    "us10y": row_10y["close"],
                    "us2y_index": row_2y["close"] / base_2y["close"] * 100,
                    "us10y_index": row_10y["close"] / base_10y["close"] * 100,
                }
            )

    phase_specs = [
        {
            "title": "1. 长端先起飞",
            "state": "短低长高",
            "period": "2020-07 到 2021-03",
            "note": "10Y 从疫情后低位先向上交易再通胀和复苏，2Y 仍贴近零利率。",
            "us10": yield_leg(us10, date(2020, 7, 1), date(2021, 3, 31), mode="low_high"),
            "us2": yield_leg(us2, date(2020, 7, 1), date(2021, 3, 31), mode="low_high"),
            "chart_start": "2020-07-01",
            "chart_end": "2021-03-31",
            "chart_points": paired_yield_points(us2, us10, date(2020, 7, 1), date(2021, 3, 31)),
            "focus_charts": [
                {
                    "label": "10Y：2020-07 到 2021-03",
                    "line": "10Y",
                    "asset": "us10y",
                    "start": "2020-07-01",
                    "end": "2021-03-31",
                    "points": single_yield_points(us10, date(2020, 7, 1), date(2021, 3, 31)),
                },
                {
                    "label": "2Y：2020-07 到 2021-03",
                    "line": "2Y",
                    "asset": "us2y",
                    "start": "2020-07-01",
                    "end": "2021-03-31",
                    "points": single_yield_points(us2, date(2020, 7, 1), date(2021, 3, 31)),
                },
            ],
        },
        {
            "title": "2. 长短端共同回落",
            "state": "短低长低",
            "period": "2021-03 到 2021-07",
            "note": "长端从 3 月高点回落；短端在 6 月冲高后也回落。",
            "us10": yield_leg(us10, date(2021, 3, 30), date(2021, 7, 31), mode="high_low"),
            "us2": yield_leg(us2, date(2021, 6, 21), date(2021, 7, 31), mode="high_low"),
            "chart_start": "2021-03-30",
            "chart_end": "2021-07-30",
            "chart_points": paired_yield_points(us2, us10, date(2021, 3, 30), date(2021, 7, 30)),
            "focus_charts": [
                {
                    "label": "10Y：2021-01 到 2021-07",
                    "line": "10Y",
                    "asset": "us10y",
                    "start": "2021-01-04",
                    "end": "2021-07-30",
                    "points": single_yield_points(us10, date(2021, 1, 4), date(2021, 7, 30)),
                },
                {
                    "label": "2Y：2021-06 到 2021-08",
                    "line": "2Y",
                    "asset": "us2y",
                    "start": "2021-06-01",
                    "end": "2021-08-31",
                    "points": single_yield_points(us2, date(2021, 6, 1), date(2021, 8, 31)),
                },
            ],
        },
        {
            "title": "3. 短端暴涨追赶",
            "state": "短高长低",
            "period": "2021-08 到 2022-02",
            "note": "市场开始集中交易加息路径，2Y 对政策利率更敏感。",
            "us10": yield_leg(us10, date(2021, 8, 1), date(2022, 2, 28), mode="low_high"),
            "us2": yield_leg(us2, date(2021, 8, 1), date(2022, 2, 28), mode="low_high"),
            "chart_start": "2021-08-01",
            "chart_end": "2022-02-28",
            "chart_points": paired_yield_points(us2, us10, date(2021, 8, 1), date(2022, 2, 28)),
            "focus_charts": [
                {
                    "label": "10Y：2021-08 到 2022-02",
                    "line": "10Y",
                    "asset": "us10y",
                    "start": "2021-08-02",
                    "end": "2022-02-28",
                    "points": single_yield_points(us10, date(2021, 8, 2), date(2022, 2, 28)),
                },
                {
                    "label": "2Y：2021-08 到 2022-02",
                    "line": "2Y",
                    "asset": "us2y",
                    "start": "2021-08-02",
                    "end": "2022-02-28",
                    "points": single_yield_points(us2, date(2021, 8, 2), date(2022, 2, 28)),
                },
            ],
        },
        {
            "title": "4. 长端补涨，价差收敛",
            "state": "短高长高",
            "period": "2022-02 到 2022-06",
            "note": "首次加息后长端补涨，10Y-2Y 价差从高位继续压缩。",
            "us10": yield_leg(us10, date(2022, 2, 28), date(2022, 6, 14), mode="close"),
            "us2": yield_leg(us2, date(2022, 2, 28), date(2022, 6, 14), mode="close"),
            "chart_start": "2022-02-28",
            "chart_end": "2022-06-14",
            "chart_points": paired_yield_points(us2, us10, date(2022, 2, 28), date(2022, 6, 14)),
            "focus_charts": [
                {
                    "label": "10Y：2022-02 到 2022-06",
                    "line": "10Y",
                    "asset": "us10y",
                    "start": "2022-02-28",
                    "end": "2022-06-14",
                    "points": single_yield_points(us10, date(2022, 2, 28), date(2022, 6, 14)),
                },
                {
                    "label": "2Y：2022-02 到 2022-06",
                    "line": "2Y",
                    "asset": "us2y",
                    "start": "2022-02-28",
                    "end": "2022-06-14",
                    "points": single_yield_points(us2, date(2022, 2, 28), date(2022, 6, 14)),
                },
            ],
        },
    ]

    spread_start_10 = at_or_before(us10, date(2022, 2, 28))
    spread_start_2 = at_or_before(us2, date(2022, 2, 28))
    spread_end_10 = at_or_before(us10, date(2022, 6, 14))
    spread_end_2 = at_or_before(us2, date(2022, 6, 14))
    spread = None
    if spread_start_10 and spread_start_2 and spread_end_10 and spread_end_2:
        spread = {
            "start_bp": (spread_start_10["close"] - spread_start_2["close"]) * 100,
            "end_bp": (spread_end_10["close"] - spread_end_2["close"]) * 100,
        }

    return {
        "source": "US2YR.OTC / US10YR.OTC 本地日线",
        "chart_start": start.isoformat(),
        "chart_end": end.isoformat(),
        "first_hike": "2022-03-16",
        "points": points,
        "phases": phase_specs,
        "spread": spread,
    }


def build_source_audit(series: dict[str, list[dict[str, Any]]], specs: dict[str, SeriesSpec]) -> list[dict[str, Any]]:
    usdrub = series.get("USDRUB") or series.get("USDRUB_YAHOO", [])
    rubcny_formula = derived_ratio("RUBCNY_AUDIT", series.get("USDCNY", []), usdrub, "USDCNY / USDRUB")
    rubjpy_formula = derived_ratio("RUBJPY_AUDIT", series.get("USDJPY", []), usdrub, "USDJPY / USDRUB")
    formula_checks = [
        ("RUBCNY", "卢布/人民币", "USDCNY/USDRUB", rubcny_formula, series.get("RUBCNY_YAHOO", [])),
        ("RUBJPY", "卢布/日元", "USDJPY/USDRUB", rubjpy_formula, series.get("RUBJPY_YAHOO", [])),
    ]

    rows: list[dict[str, Any]] = []
    for key, label, formula, formula_rows, direct_rows in formula_checks:
        comparison = compare_on_latest_common_date(formula_rows, direct_rows)
        rows.append(
            {
                "key": key,
                "label": label,
                "selected_source": specs[key].source,
                "selected_symbol": specs[key].symbol,
                "formula": formula,
                "direct_source": "yahoo",
                "direct_symbol": f"{key}=X",
                "comparison": comparison,
            }
        )

    for key, formula in [
        ("CNY_BASE", "1"),
        ("CNYJPY", "1/JPYCNY"),
        ("US_10Y2Y", "US_10Y-US_2Y"),
        ("CN_10Y2Y", "CN_10Y-CN_2Y"),
        ("JP_10Y2Y", "JP_10Y-JP_2Y"),
        ("DE_10Y2Y", "DE_10Y-DE_2Y"),
        ("RU_10Y2Y", "RU_10Y-RU_2Y"),
        ("KR_10Y2Y", "KR_10Y-KR_2Y"),
    ]:
        spec = specs.get(key)
        rows.append(
            {
                "key": key,
                "label": spec.label if spec else key,
                "selected_source": spec.source if spec else "derived",
                "selected_symbol": spec.symbol if spec else formula,
                "formula": formula,
                "direct_source": "",
                "direct_symbol": "",
                "comparison": None,
            }
        )
    return rows


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
                "count": len(series.get(key, [])),
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


def fmt_fx_price(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "缺失"
    digits = 6 if abs(value) < 0.01 else 4
    return f"{value:,.{digits}f}"


def fmt_signed_fx_price(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "缺失"
    digits = 6 if abs(value) < 0.01 else 4
    return f"{value:+,.{digits}f}"


def fmt_signed_pct(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "缺失"
    return f"{value:+.2f}%"


def value_class(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "flat"
    return "pos" if value > 0 else "neg" if value < 0 else "flat"


def fmt_fx_range(value: dict[str, Any] | None) -> str:
    if not value:
        return "缺失"
    return f"{fmt_fx_price(value.get('low'))} - {fmt_fx_price(value.get('high'))}"


def render_fx_rank_detail(code: str, fx_details: dict[str, Any]) -> str:
    detail = fx_details.get(code, {})
    rows = detail.get("rows") or []
    if not rows:
        return (
            f'<div class="fx-rank-detail" data-fx-rank-detail="{escape(code)}" hidden>'
            '<p class="muted">暂无可用交叉汇率明细。</p>'
            "</div>"
        )
    body = []
    for row in rows:
        pct_change = row.get("pct_change")
        change = row.get("change")
        cls = value_class(pct_change)
        cls_7d = value_class(row.get("pct_change_7d"))
        cls_30d = value_class(row.get("pct_change_30d"))
        body.append(
            '<div class="fx-rank-card">'
            f'<div class="fx-pair-cell"><strong>{escape(row["pair"])}</strong><span>{escape(row["name"])}</span></div>'
            '<div class="fx-rank-metrics">'
            f'<span><em>最新</em>{escape(fmt_fx_price(row.get("latest")))}</span>'
            f'<span class="{cls}"><em>变化</em>{escape(fmt_signed_fx_price(change))}</span>'
            f'<span class="{cls}"><em>涨跌幅</em>{escape(fmt_signed_pct(pct_change))}</span>'
            "</div>"
            '<div class="fx-rank-moves">'
            f'<span class="{cls_7d}"><em>7D涨跌</em>{escape(fmt_signed_pct(row.get("pct_change_7d")))}</span>'
            f'<span class="{cls_30d}"><em>30D涨跌</em>{escape(fmt_signed_pct(row.get("pct_change_30d")))}</span>'
            "</div>"
            '<div class="fx-rank-ranges">'
            f'<span><em>7D区间</em>{escape(fmt_fx_range(row.get("range_7d")))}</span>'
            f'<span><em>30D区间</em>{escape(fmt_fx_range(row.get("range_30d")))}</span>'
            "</div>"
            "</div>"
        )
    return (
        f'<div class="fx-rank-detail" data-fx-rank-detail="{escape(code)}" hidden>'
        f"{''.join(body)}"
        "</div>"
    )


def fmt_asset_volatility(summary: dict[str, Any], unit: str) -> str:
    windows = summary.get("avg_abs_vol") or {}
    return (
        '<div class="asset-vol">'
        f'<span>7D 波动 {escape(fmt_volatility_value(windows.get("7D"), unit))}</span>'
        f'<span>30D 波动 {escape(fmt_volatility_value(windows.get("30D"), unit))}</span>'
        "</div>"
    )


def policy_direction_class(value: str) -> str:
    if "加息" in value or "偏鹰" in value:
        return "pos"
    if "降息" in value or "偏鸽" in value:
        return "neg"
    return "flat"


def policy_action_class(action_type: str) -> str:
    if action_type == "加息":
        return "pos"
    if action_type == "降息":
        return "neg"
    return "flat"


def fmt_action_bp(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:+d}bp"


def render_policy_action_rows(actions: list[dict[str, Any]], *, empty_text: str) -> str:
    if not actions:
        return f'<p class="muted">{escape(empty_text)}</p>'
    html = ['<div class="policy-action-list">']
    for action in actions:
        action_type = escape(action.get("type", ""))
        action_cls = policy_action_class(action.get("type", ""))
        source_url = action.get("source_url", "")
        source = escape(action.get("source", ""))
        source_html = f'<a href="{escape(source_url)}" target="_blank" rel="noreferrer">{source}</a>' if source_url else f"<span>{source}</span>"
        html.append(
            '<div class="policy-action-row">'
            f'<time>{escape(action.get("date", ""))}</time>'
            f'<b class="{action_cls}">{action_type} {escape(fmt_action_bp(action.get("change_bp")))}</b>'
            f'<span>{escape(action.get("rate_before", ""))} -> {escape(action.get("rate_after", ""))}</span>'
            f"<small>{source_html}</small>"
            "</div>"
        )
    html.append("</div>")
    return "".join(html)


def render_policy_news(policy_news: dict[str, Any]) -> str:
    regions = policy_news.get("regions", {})
    if not regions:
        return ""
    model = escape(policy_news.get("model", ""))
    analysis_source = escape(policy_news.get("analysis_source", "规则解析"))
    news_source = escape(policy_news.get("news_source", ""))
    cache_status = escape(policy_news.get("cache_status", ""))
    html = [
        '<section class="panel policy-news-panel">',
        '<div class="policy-news-head">',
        "<div>",
        "<h2>政策新闻雷达</h2>",
        "<p>新闻态度每周自动更新；实际操作每天检查官方利率源，有变化才更新。</p>",
        f'<p class="muted">范围：美 / 欧 / 日 / 中 / 韩 / 俄；新闻源：{news_source}；分析：{analysis_source}；缓存：{cache_status}',
    ]
    if analysis_source == "OpenAI":
        html.append(f"（{model}）")
    html.extend(["</p>", "</div>", '<span class="policy-news-badge">每周更新 / OpenAI 5.4 mini</span>', "</div>"])
    html.append('<div class="policy-news-grid">')
    for code in ["US", "EU", "JP", "CN", "KR", "RU"]:
        region = regions.get(code) or {}
        items = region.get("items") or []
        top = items[0] if items else {}
        direction = str(top.get("policy_direction", "缺失"))
        stance = str(top.get("stance", ""))
        cls = policy_direction_class(f"{direction} {stance}")
        html.append('<article class="policy-card">')
        html.append(
            '<div class="policy-card-top">'
            f'<div><strong>{escape(region.get("name", code))}</strong><span>{escape(region.get("central_bank", ""))}</span></div>'
            f'<b class="{cls}">{escape(direction)}</b>'
            "</div>"
        )
        for item in items[:2]:
            item_cls = policy_direction_class(f'{item.get("policy_direction", "")} {item.get("stance", "")}')
            source = escape(item.get("source", ""))
            published = escape(item.get("published_at", ""))
            headline = escape(item.get("headline", ""))
            summary = escape(item.get("summary_cn", ""))
            url = item.get("url", "")
            html.append('<div class="policy-news-item">')
            if url:
                html.append(f'<a href="{escape(url)}" target="_blank" rel="noreferrer">{headline}</a>')
            else:
                html.append(f"<span>{headline}</span>")
            html.append(
                '<div class="policy-news-meta">'
                f'<em class="{item_cls}">{escape(item.get("stance", ""))}</em>'
                f'<small>{source}</small>'
                f'<small>{published}</small>'
                "</div>"
            )
            if summary:
                html.append(f'<p class="muted">{summary}</p>')
            html.append("</div>")
        actions = region.get("actions") or []
        recent_year_actions = region.get("recent_year_actions") or []
        action_cache_status = escape(region.get("action_cache_status", ""))
        action_last_changed_at = escape(region.get("action_last_changed_at", ""))
        html.append('<div class="policy-actions">')
        html.append(
            '<div class="policy-actions-head">'
            "<strong>实际操作</strong>"
            f'<span>政策工具：{escape(region.get("policy_tool", ""))}</span>'
            "</div>"
        )
        html.append(render_policy_action_rows(actions[:3], empty_text="暂无可显示的加息/降息记录。"))
        html.append(
            '<div class="policy-action-meta">'
            f"<span>检查状态：{action_cache_status or 'fallback'}</span>"
            f"<span>上次变化：{action_last_changed_at or '缺失'}</span>"
            "</div>"
        )
        html.append(
            f'<button type="button" class="policy-actions-toggle" data-policy-actions-toggle="{escape(code)}">'
            "查看近一年实际操作"
            "</button>"
        )
        html.append(f'<div class="policy-actions-expanded" data-policy-actions-expanded="{escape(code)}" hidden>')
        html.append(render_policy_action_rows(recent_year_actions, empty_text="近一年无加息/降息操作。"))
        html.append("</div>")
        html.append("</div>")
        html.append("</article>")
    html.extend(["</div>", "</section>"])
    return "".join(html)


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


def fmt_hike_pct(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "缺失"
    return f"{value:+.1f}%"


def fmt_hike_bp(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "缺失"
    return f"{value:+.1f}bp"


def render_hike_leg(label: str, leg: dict[str, Any] | None) -> str:
    if not leg:
        return f'<div class="hike-leg"><span>{escape(label)}</span><strong>缺失</strong></div>'
    cls = "pos" if (leg.get("pct") or 0) > 0 else "neg" if (leg.get("pct") or 0) < 0 else "flat"
    return (
        '<div class="hike-leg">'
        f'<span>{escape(label)}</span>'
        f'<strong>{leg["start"]:.3f}% -> {leg["end"]:.3f}%</strong>'
        f'<em class="{cls}">{fmt_hike_pct(leg.get("pct"))} / {fmt_hike_bp(leg.get("bp"))}</em>'
        f'<small>{escape(leg["start_date"])} -> {escape(leg["end_date"])}</small>'
        "</div>"
    )


def render_hike_chart(example: dict[str, Any]) -> str:
    points = example.get("points") or []
    if len(points) < 2:
        return '<div class="hike-chart-empty">缺少 US 2Y/10Y 历史数据。</div>'

    sampled = points[::5]
    if sampled[-1]["date"] != points[-1]["date"]:
        sampled.append(points[-1])
    width, height = 760, 270
    left, right, top, bottom = 54, 18, 18, 42
    plot_w = width - left - right
    plot_h = height - top - bottom
    start_ord = date.fromisoformat(points[0]["date"]).toordinal()
    end_ord = date.fromisoformat(points[-1]["date"]).toordinal()
    values = [point["us2y_index"] for point in sampled] + [point["us10y_index"] for point in sampled]
    log_min = math.log(max(1, min(values) * 0.9))
    log_max = math.log(max(values) * 1.08)
    if log_max == log_min:
        log_max += 1

    def xy(point: dict[str, Any], key: str) -> tuple[float, float]:
        current_ord = date.fromisoformat(point["date"]).toordinal()
        x = left + (current_ord - start_ord) / max(1, end_ord - start_ord) * plot_w
        y = top + (log_max - math.log(max(1e-9, point[key]))) / (log_max - log_min) * plot_h
        return x, y

    def path_for(key: str) -> str:
        coords = [xy(point, key) for point in sampled]
        return " ".join(("M" if index == 0 else "L") + f"{x:.1f},{y:.1f}" for index, (x, y) in enumerate(coords))

    def marker_x(date_text: str) -> float:
        current_ord = date.fromisoformat(date_text).toordinal()
        return left + (current_ord - start_ord) / max(1, end_ord - start_ord) * plot_w

    first_hike_x = marker_x(example["first_hike"])
    y_ticks = [100, 200, 500, 1000, 2000]
    tick_html = []
    for tick in y_ticks:
        if math.log(tick) < log_min or math.log(tick) > log_max:
            continue
        y = top + (log_max - math.log(tick)) / (log_max - log_min) * plot_h
        tick_html.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" class="hike-grid-line" />'
            f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{tick}</text>'
        )

    svg = (
        f'<svg class="hike-chart" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="2022 加息周期美国 2Y 与 10Y 国债收益率归一化走势">'
        f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" class="hike-chart-bg" />'
        + "".join(tick_html)
        + f'<line x1="{first_hike_x:.1f}" y1="{top}" x2="{first_hike_x:.1f}" y2="{top + plot_h}" class="hike-event-line" />'
        + f'<path d="{path_for("us10y_index")}" class="hike-line hike-line-10y" />'
        + f'<path d="{path_for("us2y_index")}" class="hike-line hike-line-2y" />'
        + f'<text x="{left}" y="{height - 14}" class="hike-axis-label">{escape(example["chart_start"])}</text>'
        + f'<text x="{width - right}" y="{height - 14}" text-anchor="end" class="hike-axis-label">{escape(example["chart_end"])}</text>'
        + f'<text x="{left}" y="12" class="hike-axis-label">指数，2020-07-01=100，对数刻度</text>'
        + '</svg>'
    )
    return (
        '<div class="hike-overview-wrap">'
        '<div class="hike-overview-legend">'
        '<span><i class="legend-line legend-line-10y"></i>10Y</span>'
        '<span><i class="legend-line legend-line-2y"></i>2Y</span>'
        '</div>'
        + svg
        + '<div class="hike-event-note">虚线：2022-03-16 首次加息</div>'
        + '</div>'
    )


def render_hike_phase_chart(phase: dict[str, Any], index: int) -> str:
    points = phase.get("chart_points") or []
    if len(points) < 2:
        return '<div class="hike-phase-chart-empty">阶段收益率走势缺失。</div>'

    sampled = points[::2]
    if sampled[-1]["date"] != points[-1]["date"]:
        sampled.append(points[-1])
    width, height = 420, 150
    left, right, top, bottom = 38, 12, 14, 26
    plot_w = width - left - right
    plot_h = height - top - bottom
    start_ord = date.fromisoformat(points[0]["date"]).toordinal()
    end_ord = date.fromisoformat(points[-1]["date"]).toordinal()
    values = [point["us2y"] for point in sampled] + [point["us10y"] for point in sampled]
    y_min = min(values)
    y_max = max(values)
    pad = max(0.05, (y_max - y_min) * 0.12)
    y_min = max(0, y_min - pad)
    y_max += pad
    if y_max == y_min:
        y_max += 0.1

    def xy(point: dict[str, Any], key: str) -> tuple[float, float]:
        current_ord = date.fromisoformat(point["date"]).toordinal()
        x = left + (current_ord - start_ord) / max(1, end_ord - start_ord) * plot_w
        y = top + (y_max - point[key]) / (y_max - y_min) * plot_h
        return x, y

    def path_for(key: str) -> str:
        coords = [xy(point, key) for point in sampled]
        return " ".join(("M" if item_index == 0 else "L") + f"{x:.1f},{y:.1f}" for item_index, (x, y) in enumerate(coords))

    top_label = f"{y_max:.2f}%"
    bottom_label = f"{y_min:.2f}%"
    svg = (
        f'<svg class="hike-phase-chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(phase["title"])} 阶段收益率走势">'
        f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" class="hike-chart-bg" />'
        f'<line x1="{left}" y1="{top}" x2="{width - right}" y2="{top}" class="hike-grid-line" />'
        f'<line x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}" class="hike-grid-line" />'
        f'<text x="{left - 7}" y="{top + 4}" text-anchor="end">{top_label}</text>'
        f'<text x="{left - 7}" y="{top + plot_h + 4}" text-anchor="end">{bottom_label}</text>'
        f'<path d="{path_for("us10y")}" class="hike-line hike-line-10y" />'
        f'<path d="{path_for("us2y")}" class="hike-line hike-line-2y" />'
        f'<text x="{left}" y="{height - 8}" class="hike-axis-label">{escape(phase["chart_start"])}</text>'
        f'<text x="{width - right}" y="{height - 8}" text-anchor="end" class="hike-axis-label">{escape(phase["chart_end"])}</text>'
        f'<text x="{width - right - 76}" y="11" class="hike-phase-caption">10Y</text>'
        f'<text x="{width - right - 36}" y="11" class="hike-phase-caption">2Y</text>'
        "</svg>"
    )
    return f'<div class="hike-chart-wrap"><div class="hike-chart-label">阶段收益率走势</div>{svg}</div>'


def render_hike_focus_chart(chart: dict[str, Any]) -> str:
    raw_points = chart.get("points") or []
    if len(raw_points) < 2:
        return '<div class="hike-phase-chart-empty">焦点收益率走势缺失。</div>'

    mode = chart.get("mode") or "yield"
    base_value = raw_points[0]["value"] or 1
    points = []
    for point in raw_points:
        value = point["value"] / base_value * 100 if mode == "index" else point["value"]
        points.append({"date": point["date"], "value": value})

    sampled = points[::2]
    if sampled[-1]["date"] != points[-1]["date"]:
        sampled.append(points[-1])
    width, height = 420, 150
    left, right, top, bottom = 42, 12, 18, 26
    plot_w = width - left - right
    plot_h = height - top - bottom
    start_ord = date.fromisoformat(points[0]["date"]).toordinal()
    end_ord = date.fromisoformat(points[-1]["date"]).toordinal()
    values = [point["value"] for point in sampled]
    y_min = min(values)
    y_max = max(values)
    pad = max(0.05 if mode != "index" else 10, (y_max - y_min) * 0.12)
    y_min = max(0, y_min - pad)
    y_max += pad
    if y_max == y_min:
        y_max += 0.1

    def xy(point: dict[str, Any]) -> tuple[float, float]:
        current_ord = date.fromisoformat(point["date"]).toordinal()
        x = left + (current_ord - start_ord) / max(1, end_ord - start_ord) * plot_w
        y = top + (y_max - point["value"]) / (y_max - y_min) * plot_h
        return x, y

    coords = [xy(point) for point in sampled]
    path = " ".join(("M" if item_index == 0 else "L") + f"{x:.1f},{y:.1f}" for item_index, (x, y) in enumerate(coords))
    line_class = "hike-line-2y" if chart.get("asset") == "us2y" else "hike-line-10y"
    unit = "指数" if mode == "index" else "%"
    top_label = f"{y_max:.0f}" if mode == "index" else f"{y_max:.2f}%"
    bottom_label = f"{y_min:.0f}" if mode == "index" else f"{y_min:.2f}%"
    svg = (
        f'<svg class="hike-phase-chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(chart["label"])} 焦点收益率走势">'
        f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" class="hike-chart-bg" />'
        f'<line x1="{left}" y1="{top}" x2="{width - right}" y2="{top}" class="hike-grid-line" />'
        f'<line x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}" class="hike-grid-line" />'
        f'<text x="{left - 7}" y="{top + 4}" text-anchor="end">{top_label}</text>'
        f'<text x="{left - 7}" y="{top + plot_h + 4}" text-anchor="end">{bottom_label}</text>'
        f'<path d="{path}" class="hike-line {line_class}" />'
        f'<text x="{left}" y="{height - 8}" class="hike-axis-label">{escape(chart["start"])}</text>'
        f'<text x="{width - right}" y="{height - 8}" text-anchor="end" class="hike-axis-label">{escape(chart["end"])}</text>'
        f'<text x="{width - right}" y="11" text-anchor="end" class="hike-phase-caption">{escape(unit)}</text>'
        "</svg>"
    )
    return f'<div class="hike-chart-wrap"><div class="hike-chart-label">{escape(chart["label"])}</div>{svg}</div>'


def render_hike_phase_charts(phase: dict[str, Any]) -> str:
    focus_charts = phase.get("focus_charts") or []
    if focus_charts:
        default_chart = render_hike_phase_chart(phase, 0) if phase.get("include_default_chart") else ""
        return default_chart + '<div class="hike-focus-grid">' + "".join(render_hike_focus_chart(chart) for chart in focus_charts) + "</div>"
    return render_hike_phase_chart(phase, 0)


def render_hike_cycle_example(example: dict[str, Any]) -> str:
    if not example:
        return ""
    spread = example.get("spread") or {}
    spread_text = ""
    if spread:
        spread_text = f'；10Y-2Y 价差 {spread["start_bp"]:.1f}bp -> {spread["end_bp"]:.1f}bp'
    html = [
        '<div class="hike-example">',
        '<div class="hike-example-head">',
        "<h4>2022 加息周期长短债例子</h4>",
        f'<span>{escape(example["source"])}</span>',
        "</div>",
        render_hike_chart(example),
        '<div class="hike-phase-grid">',
    ]
    for phase in example.get("phases", []):
        html.append(
            '<div class="hike-phase">'
            f'<div class="hike-phase-title"><strong>{escape(phase["title"])}</strong><b>{escape(phase["state"])}</b></div>'
            f'<p class="muted">{escape(phase["period"])}｜{escape(phase["note"])}</p>'
            + render_hike_phase_charts(phase)
            + render_hike_leg("10Y", phase.get("us10"))
            + render_hike_leg("2Y", phase.get("us2"))
            + "</div>"
        )
    html.extend(
        [
            "</div>",
            f'<p class="hike-example-note">阶段算法：第一/三段取区间低点到高点；第二段取高点到低点；第四段取区间 close 起止{escape(spread_text)}。</p>',
            "</div>",
        ]
    )
    return "".join(html)


def render_html(snapshot: dict[str, Any]) -> str:
    countries = snapshot["countries"]
    rankings = snapshot["volatility_rankings"]
    fx_rank_details = snapshot.get("fx_rank_details", {})
    second_order = snapshot["second_order_monitor"]
    flow_json = json.dumps(snapshot["fx_flows"], ensure_ascii=False).replace("</", "<\\/")
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

    html.append(render_policy_news(snapshot.get("policy_news", {})))

    html.extend(
        [
            '<details class="panel volatility-panel">',
            '<summary><span>波动率排名</span><small>点击展开各国家 7D / 30D 排名</small></summary>',
            '<div class="ranking-grid">',
        ]
    )
    ranking_titles = {"bond": "债市波动率排名", "equity": "股指波动率排名", "fx": "汇率波动率排名"}
    for key in ["bond", "equity", "fx"]:
        rows = rankings.get(key, [])
        html.append('<div class="ranking-block">')
        html.append(f'<h3>{escape(ranking_titles[key])}</h3>')
        html.append('<div class="rank-row rank-head"><span>#</span><span>国家</span><span>7D</span><span>30D</span></div>')
        for row in rows:
            unit = row["unit"]
            windows = row["windows"]
            if key == "fx":
                code = row.get("code", "")
                html.append(
                    '<button type="button" class="rank-row rank-trigger" '
                    f'data-fx-rank-toggle="{escape(code)}" aria-expanded="false">'
                    f'<span>{row["rank"]}</span>'
                    f'<strong><span class="toggle-icon">▸</span>{escape(row["country"])}</strong>'
                    f'<span>{escape(fmt_volatility_value(windows.get("7D"), unit))}</span>'
                    f'<span>{escape(fmt_volatility_value(windows.get("30D"), unit))}</span>'
                    "</button>"
                )
                html.append(render_fx_rank_detail(str(code), fx_rank_details))
            else:
                html.append(
                    '<div class="rank-row">'
                    f'<span>{row["rank"]}</span>'
                    f'<strong>{escape(row["country"])}</strong>'
                    f'<span>{escape(fmt_volatility_value(windows.get("7D"), unit))}</span>'
                    f'<span>{escape(fmt_volatility_value(windows.get("30D"), unit))}</span>'
                    "</div>"
                )
        html.append("</div>")
    html.extend(["</div></details>"])

    html.extend(['<section class="panel">', "<h2>一阶/二阶监控</h2>", '<div class="math-note">'])
    html.append("D1 是窗口速度；D2 是速度变化率。债券曲线使用 10Y-2Y，便于观察长短端价差变化速度。")
    html.extend(['</div>', '<div class="table-wrap">', '<table class="derivative-table">'])
    html.append("<thead><tr><th>国家</th><th>类型</th><th>标的</th><th>1D</th><th>7D</th><th>30D</th></tr></thead><tbody>")
    second_order_by_country: dict[str, list[dict[str, Any]]] = {}
    for row in second_order:
        second_order_by_country.setdefault(row["country"], []).append(row)
    for country in [item["name"] for item in COUNTRIES]:
        country_rows = second_order_by_country.get(country, [])
        if not country_rows:
            continue
        expanded = country == "美国"
        toggle_class = "country-toggle expanded" if expanded else "country-toggle collapsed"
        toggle_icon = "▾" if expanded else "▸"
        html.append(
            f'<tr class="country-group-row" data-country="{escape(country)}">'
            '<th colspan="6">'
            f'<button type="button" class="{toggle_class}" data-country="{escape(country)}" aria-expanded="{str(expanded).lower()}">'
            f'<span class="toggle-icon">{toggle_icon}</span>'
            f'<strong>{escape(country)}</strong>'
            f'<span>{len(country_rows)} 项监控</span>'
            "</button>"
            "</th></tr>"
        )
        hidden_attr = "" if expanded else " hidden"
        for row in country_rows:
            volatility = ""
            if row.get("summary"):
                volatility = fmt_asset_volatility(row["summary"], row["unit"])
            html.append(
                f'<tr class="derivative-row" data-country="{escape(country)}" data-ohlc-key="{escape(row["key"])}" title="点击查看日线 OHLC"{hidden_attr}>'
                f'<th>{escape(row["country"])}</th>'
                f'<td>{escape(row["group"])}</td>'
                f'<td><div>{escape(row["label"])}</div>{volatility}</td>'
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
            '<div class="ohlc-toolbar">',
            '<div class="segmented" aria-label="OHLC 图表模式">',
            '<button type="button" class="ohlc-mode active" data-mode="move">涨跌幅</button>',
            '<button type="button" class="ohlc-mode" data-mode="ohlc">K线</button>',
            "</div>",
            '<div class="segmented" aria-label="OHLC 时间窗口">',
            '<button type="button" class="ohlc-window active" data-window="90">90D</button>',
            '<button type="button" class="ohlc-window" data-window="180">180D</button>',
            '<button type="button" class="ohlc-window" data-window="360">360D</button>',
            "</div>",
            '<div class="chart-tools">',
            '<button type="button" id="ohlc-zoom-in" title="放大">+</button>',
            '<button type="button" id="ohlc-zoom-out" title="缩小">-</button>',
            '<button type="button" id="ohlc-reset">Reset</button>',
            '<span id="ohlc-range-label"></span>',
            "</div>",
            "</div>",
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
                f'<div class="date">{escape(summary.get("date") or "")}</div></td>'
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
    for section_index, section in enumerate(snapshot["fx_flows"]):
        html.append('<div class="flow-block">')
        html.append(f'<h3>{escape(section["name"])}</h3>')
        for period_index, period in enumerate(section["periods"]):
            html.append('<div class="flow-row">')
            html.append(f'<div class="period">{escape(period["period"])}</div>')
            result = period["result"]
            if result and result["best_route"]:
                best = result["best_route"]
                ranking = " > ".join(result["ranking"])
                html.append(
                    '<div class="flow-cell">'
                    f'<div><strong>{escape(best["label"])}</strong> '
                    f'<span class="pos">{best["score"]:+.4f}</span></div>'
                    f'<div class="muted">强弱：{escape(ranking)}</div>'
                    f'<button type="button" class="flow-expand" data-flow-section="{section_index}" '
                    f'data-flow-period="{period_index}" aria-expanded="false">'
                    '<span class="toggle-icon">▸</span><span>查看6条路线</span>'
                    "</button>"
                    f'<div class="flow-routes" hidden data-flow-routes="{section_index}-{period_index}">'
                )
                for route_index, route in enumerate(result["routes"]):
                    score_cls = "pos" if route["score"] >= 0 else "neg"
                    status = "成立" if route["score"] > 0 else "不成立" if route["score"] < 0 else "临界"
                    html.append(
                        f'<button type="button" class="flow-route" data-flow-section="{section_index}" '
                        f'data-flow-period="{period_index}" data-flow-route="{route_index}">'
                        f'<span>{escape(route["label"])}</span>'
                        f'<span class="{score_cls}">{route["score"]:+.4f}</span>'
                        f'<span class="route-status">{escape(status)}</span>'
                        "</button>"
                    )
                html.append("</div></div>")
            else:
                html.append(f'<div class="muted">缺少：{escape(", ".join(period["missing"]))}</div>')
            html.append("</div>")
        html.append("</div>")
    html.extend(
        [
            "</div>",
            "</section>",
        ]
    )

    hedge_cycles = [
        (
            "降息周期",
            [
                ("第一种", "降息卖短买长", "短债收益率走高，长债收益率走低，交易降息预期。", "短高长低"),
                ("第二种", "扩表卖长债", "长债收益率走高，长短债收益率都走高。", "短高长高"),
                ("第三种", "继续扩表卖长债", "当长短债同幅高位，市场会优先买较高收益率短债。", "短低长高"),
                ("第四种", "停止卖出", "降息中不降息，自然压低债券收益率，阶段性扩表完成。", "短低长低"),
            ],
        ),
        (
            "加息周期",
            [
                ("第一种", "短端低，长端高", "长端仍反映期限溢价或供给压力，曲线偏陡。", "短低长高"),
                ("第二种", "短端低，长端低", "长短端同步低位，政策和增长预期都偏弱。", "短低长低"),
                ("第三种", "短端高，长端低", "第一次加息常见长短债交叉，短端更快交易政策利率。", "短高长低"),
                ("第四种", "短端高，长端高", "长短端同步高位，市场同时定价加息和期限压力。", "短高长高"),
            ],
        ),
    ]
    html.extend(['<section class="panel hedge-cycle-panel">', "<h2>长短债 8 种对冲</h2>"])
    for cycle_title, cases in hedge_cycles:
        html.append('<div class="hedge-cycle-block">')
        html.append(f"<h3>{escape(cycle_title)}</h3>")
        html.append('<div class="hedge-case-grid">')
        for index, action, detail, state in cases:
            html.append(
                '<div class="hedge-case">'
                f'<div><strong>{escape(index)}</strong><span>{escape(action)}</span></div>'
                f'<p>{escape(detail)}</p>'
                f'<b>{escape(state)}</b>'
                "</div>"
            )
        html.append("</div>")
        if cycle_title == "加息周期":
            html.append(render_hike_cycle_example(snapshot.get("hike_cycle_example", {})))
        html.append("</div>")
    html.append('<p class="hedge-footnote">前两种偏缩，后两种偏扩；第一次加息常见长短债交叉。</p>')
    html.append("</section>")

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
    html.append("</section>")

    html.extend(
        [
            f'<script id="ohlc-data" type="application/json">{ohlc_json}</script>',
            f'<script id="fx-flow-data" type="application/json">{flow_json}</script>',
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
.policy-news-panel { margin-top: 0; }
.policy-news-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 12px; }
.policy-news-head h2 { margin-bottom: 4px; }
.policy-news-badge { border: 1px solid #c8d4e2; border-radius: 999px; padding: 4px 9px; color: var(--blue); background: #f8fafc; font-size: 12px; font-weight: 700; white-space: nowrap; }
.policy-news-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.policy-card { border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 10px; min-width: 0; }
.policy-card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding-bottom: 8px; border-bottom: 1px solid #eef2f7; }
.policy-card-top strong { display: block; font-size: 14px; }
.policy-card-top span { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
.policy-card-top b { font-size: 12px; white-space: nowrap; }
.policy-news-item { display: grid; gap: 5px; padding-top: 8px; min-width: 0; }
.policy-news-item a, .policy-news-item > span { color: var(--ink); text-decoration: none; font-weight: 650; line-height: 1.35; overflow-wrap: anywhere; }
.policy-news-item a:hover { color: var(--blue); text-decoration: underline; }
.policy-news-item p { margin: 0; font-size: 12px; line-height: 1.35; }
.policy-news-meta { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 11px; min-width: 0; flex-wrap: wrap; }
.policy-news-meta em { font-style: normal; font-weight: 700; }
.policy-actions { margin-top: 10px; padding-top: 9px; border-top: 1px solid #eef2f7; }
.policy-actions-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 7px; }
.policy-actions-head strong { font-size: 12px; }
.policy-actions-head span { color: var(--muted); font-size: 11px; text-align: right; overflow-wrap: anywhere; }
.policy-action-list { display: grid; gap: 5px; }
.policy-action-row {
  display: grid;
  grid-template-columns: 78px 78px minmax(92px, 1fr) auto;
  gap: 6px;
  align-items: baseline;
  border: 1px solid #eef2f7;
  border-radius: 6px;
  padding: 5px 6px;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.policy-action-row time { color: var(--muted); }
.policy-action-row b { white-space: nowrap; }
.policy-action-row span { color: var(--ink); overflow-wrap: anywhere; }
.policy-action-row small { color: var(--muted); text-align: right; }
.policy-action-row a { color: var(--muted); text-decoration: none; }
.policy-action-row a:hover { color: var(--blue); text-decoration: underline; }
.policy-action-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; color: var(--muted); font-size: 11px; }
.policy-actions-toggle {
  margin-top: 7px;
  border: 1px solid #d5dde8;
  border-radius: 6px;
  background: #fff;
  color: var(--blue);
  cursor: pointer;
  font-size: 12px;
  font-weight: 750;
  padding: 6px 8px;
}
.policy-actions-toggle:hover { background: #f8fafc; border-color: #b7c2cf; }
.policy-actions-expanded { margin-top: 7px; }
.volatility-panel { padding: 0; overflow: hidden; }
.volatility-panel summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer; padding: 16px; font-weight: 750; list-style: none; }
.volatility-panel summary::-webkit-details-marker { display: none; }
.volatility-panel summary:hover { background: #f8fafc; }
.volatility-panel summary small { color: var(--muted); font-size: 12px; font-weight: 600; }
.volatility-panel .ranking-grid { padding: 0 16px 16px; }
.ranking-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
.ranking-block + .ranking-block { border-left: 1px solid var(--line); padding-left: 18px; }
.rank-row { display: grid; grid-template-columns: 28px minmax(58px, 1fr) minmax(76px, auto) minmax(76px, auto); gap: 8px; align-items: baseline; padding: 5px 0; font-variant-numeric: tabular-nums; }
.rank-row span:nth-child(n+3) { text-align: right; }
.rank-head { color: var(--muted); font-size: 12px; font-weight: 650; border-bottom: 1px solid var(--line); margin-bottom: 4px; }
.rank-trigger { width: 100%; border: 0; background: transparent; color: inherit; cursor: pointer; font: inherit; text-align: left; }
.rank-trigger:hover { background: #f8fafc; border-radius: 6px; }
.rank-trigger strong { display: inline-flex; align-items: center; gap: 4px; min-width: 0; }
.rank-trigger .toggle-icon { color: var(--blue); font-size: 11px; line-height: 1; text-align: left; }
.fx-rank-detail { margin: 4px 0 8px 28px; border: 1px solid var(--line); border-radius: 8px; background: #fff; overflow: hidden; }
.fx-rank-detail p { margin: 10px; }
.fx-rank-card { display: grid; gap: 7px; padding: 10px; border-bottom: 1px solid #eef2f7; font-size: 12px; }
.fx-rank-card:last-child { border-bottom: 0; }
.fx-pair-cell strong { display: block; color: var(--ink); font-size: 13px; }
.fx-pair-cell span { display: block; color: var(--muted); font-size: 11px; margin-top: 2px; }
.fx-rank-metrics, .fx-rank-moves, .fx-rank-ranges { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; font-variant-numeric: tabular-nums; }
.fx-rank-moves,
.fx-rank-ranges { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.fx-rank-metrics span, .fx-rank-moves span, .fx-rank-ranges span { min-width: 0; white-space: normal; overflow-wrap: anywhere; }
.fx-rank-metrics em, .fx-rank-moves em, .fx-rank-ranges em { display: block; color: var(--muted); font-style: normal; font-size: 10px; line-height: 1.2; }
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
.country-group-row th { background: #f9fafb; padding: 0; }
.country-toggle {
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--ink);
  cursor: pointer;
  display: grid;
  grid-template-columns: 20px minmax(80px, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 10px 8px;
  text-align: left;
  font: inherit;
}
.country-toggle strong { font-size: 14px; }
.country-toggle span:last-child { color: var(--muted); font-size: 12px; font-weight: 650; }
.country-toggle.expanded { background: #edf4ff; color: var(--blue); }
.country-toggle.collapsed:hover { background: #f3f6fa; }
.toggle-icon { color: var(--blue); font-size: 13px; text-align: center; }
.derivative-row { cursor: pointer; }
.derivative-row[hidden] { display: none; }
.derivative-row:hover { background: #f3f6fa; }
.derivative-row.selected { background: #eaf2ff; }
.deriv-cell { display: grid; gap: 2px; font-size: 12px; line-height: 1.35; min-width: 134px; }
.deriv-cell .tag { margin-top: 2px; }
.ohlc-panel { scroll-margin-top: 18px; }
.ohlc-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: -2px 0 12px; flex-wrap: wrap; }
.segmented, .chart-tools { display: flex; align-items: center; gap: 6px; }
.ohlc-toolbar button { border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--ink); cursor: pointer; min-width: 34px; height: 30px; padding: 0 10px; font: inherit; font-size: 12px; font-weight: 650; }
.ohlc-toolbar button.active { background: #eaf2ff; border-color: #aac5ee; color: var(--blue); }
#ohlc-range-label { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.ohlc-head { color: var(--muted); margin: -4px 0 12px; font-size: 13px; }
.chart-shell { position: relative; border: 1px solid var(--line); border-radius: 8px; background: #fff; overflow: hidden; }
#ohlc-chart { display: block; width: 100%; height: min(52vw, 420px); min-height: 320px; cursor: grab; }
#ohlc-chart.dragging { cursor: grabbing; }
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
.chart-tooltip.dark {
  background: rgba(15, 23, 42, 0.92);
  border-color: rgba(15, 23, 42, 0.92);
  color: #fff;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.28);
}
.chart-tooltip.dark .muted { color: #cbd5e1; }
.flow-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.flow-block { padding: 12px; }
.flow-row { display: grid; grid-template-columns: 52px 1fr; gap: 10px; border-top: 1px solid var(--line); padding: 10px 0 0; margin-top: 10px; }
.period { color: var(--blue); font-weight: 700; }
.flow-cell { min-width: 0; }
.flow-expand {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 6px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--blue);
  padding: 5px 8px;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.flow-expand:hover { background: #f8fafc; border-color: #b7c2cf; }
.flow-routes { display: grid; gap: 5px; margin-top: 8px; }
.flow-routes[hidden] { display: none; }
.flow-route {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  padding: 6px 8px;
  color: var(--ink);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.flow-route:hover { border-color: #b7c2cf; background: #f8fafc; }
.flow-route.selected { border-color: var(--blue); background: #eaf2ff; }
.flow-route span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.route-status { color: var(--muted); font-size: 11px; }
.flow-route-detail {
  margin: 2px 0 8px;
  border: 1px solid #c8d4e2;
  border-radius: 8px;
  background: #f8fafc;
  padding: 10px;
}
.flow-route-detail[hidden] { display: none; }
.flow-detail-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 12px; }
.flow-route-detail .flow-detail-grid { grid-template-columns: 1fr; }
.flow-detail-card { border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 12px; }
.flow-detail-card h4 { margin: 0 0 8px; font-size: 13px; letter-spacing: 0; }
.flow-detail-card p { margin: 5px 0; }
.flow-detail-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.flow-detail-table th, .flow-detail-table td { border-bottom: 1px solid var(--line); padding: 6px 4px; text-align: left; }
.flow-detail-table th:last-child, .flow-detail-table td:last-child { text-align: right; }
.formula-line { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.flow-calc-toggle {
  margin-top: 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--blue);
  padding: 6px 9px;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.flow-calc-toggle:hover { background: #f8fafc; border-color: #b7c2cf; }
.flow-calc-more { margin-top: 10px; }
.flow-calc-more[hidden] { display: none; }
.status-table th, .status-table td { text-align: left; }
.notes { color: var(--muted); font-size: 13px; margin: 14px 0 0; }
.notes p { margin: 4px 0; }
.hedge-cycle-panel h2 { margin-bottom: 12px; }
.hedge-cycle-block + .hedge-cycle-block { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--line); }
.hedge-cycle-block h3 { margin: 0 0 10px; font-size: 15px; letter-spacing: 0; }
.hedge-case-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.hedge-case {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  padding: 10px;
  display: grid;
  gap: 6px;
}
.hedge-case div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.hedge-case strong { color: var(--blue); white-space: nowrap; }
.hedge-case span { font-weight: 700; text-align: right; }
.hedge-case p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.45; }
.hedge-case b { justify-self: start; color: var(--ink); background: #eef2f7; border-radius: 6px; padding: 3px 7px; font-size: 12px; }
.hedge-footnote { margin: 12px 0 0; color: var(--muted); font-size: 12px; }
.hike-example { margin-top: 12px; border-top: 1px solid var(--line); padding-top: 12px; }
.hike-example-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.hike-example-head h4 { margin: 0; font-size: 14px; letter-spacing: 0; }
.hike-example-head span { color: var(--muted); font-size: 12px; text-align: right; }
.hike-overview-wrap { border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 8px; }
.hike-overview-legend { display: flex; justify-content: flex-end; gap: 16px; align-items: center; margin-bottom: 4px; color: var(--ink); font-size: 12px; font-weight: 700; }
.hike-overview-legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend-line { display: inline-block; width: 26px; height: 3px; border-radius: 999px; }
.legend-line-10y { background: #2563eb; }
.legend-line-2y { background: #dc2626; }
.hike-chart { width: 100%; height: auto; display: block; background: #fff; }
.hike-chart-bg { fill: #fbfcfe; }
.hike-grid-line { stroke: #e5e9ef; stroke-width: 1; }
.hike-chart text { fill: var(--muted); font-size: 11px; }
.hike-line { fill: none; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
.hike-line-10y { stroke: #2563eb; }
.hike-line-2y { stroke: #dc2626; }
.hike-event-line { stroke: #64748b; stroke-width: 1.2; stroke-dasharray: 4 4; }
.hike-event-note { color: var(--muted); font-size: 12px; margin-top: 4px; text-align: right; }
.hike-phase-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 8px; }
.hike-phase { border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 10px; }
.hike-phase-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 5px; }
.hike-phase-title strong { font-size: 13px; }
.hike-phase-title b { color: var(--blue); background: #eaf2ff; border-radius: 6px; padding: 3px 7px; font-size: 12px; white-space: nowrap; }
.hike-chart-wrap { margin: 8px 0; }
.hike-chart-label { color: var(--ink); font-weight: 700; font-size: 12px; line-height: 1.35; margin-bottom: 4px; overflow-wrap: anywhere; }
.hike-phase-chart { width: 100%; height: auto; display: block; border: 1px solid #eef2f7; border-radius: 6px; background: #fff; }
.hike-phase-chart text { fill: var(--muted); font-size: 10px; }
.hike-phase-caption { font-weight: 700; }
.hike-phase-chart-empty { margin: 8px 0; color: var(--muted); font-size: 12px; }
.hike-focus-grid { display: grid; gap: 8px; }
.hike-leg { display: grid; grid-template-columns: 32px minmax(0, 1fr) auto; gap: 8px; align-items: baseline; padding-top: 6px; border-top: 1px solid #eef2f7; }
.hike-leg span { color: var(--muted); font-weight: 700; }
.hike-leg strong { font-size: 12px; }
.hike-leg em { font-style: normal; font-weight: 700; font-size: 12px; }
.hike-leg small { grid-column: 2 / 4; color: var(--muted); font-size: 11px; }
.hike-example-note { margin: 8px 0 0; color: var(--muted); font-size: 12px; }
@media (max-width: 900px) {
  main { padding: 14px; }
  .topbar { align-items: flex-start; flex-direction: column; }
  .policy-news-head { align-items: flex-start; flex-direction: column; }
  .policy-news-grid, .ranking-grid, .flow-grid { grid-template-columns: 1fr; }
  .policy-actions-head { align-items: flex-start; flex-direction: column; }
  .policy-actions-head span { text-align: left; }
  .policy-action-row { grid-template-columns: 78px 78px minmax(0, 1fr); }
  .policy-action-row small { grid-column: 1 / 4; text-align: left; }
  .flow-detail-grid { grid-template-columns: 1fr; }
  .hedge-case-grid { grid-template-columns: 1fr; }
  .hike-example-head { align-items: flex-start; flex-direction: column; }
  .hike-phase-grid { grid-template-columns: 1fr; }
  .ranking-block + .ranking-block { border-left: 0; border-top: 1px solid var(--line); padding-left: 0; padding-top: 12px; }
}
"""


JS = """
(() => {
  const raw = document.getElementById("ohlc-data")?.textContent || "{}";
  const ohlcData = JSON.parse(raw);
  const flowRaw = document.getElementById("fx-flow-data")?.textContent || "[]";
  const flowData = JSON.parse(flowRaw);
  const rows = Array.from(document.querySelectorAll(".derivative-row"));
  const countryToggles = Array.from(document.querySelectorAll(".country-toggle"));
  const flowExpandButtons = Array.from(document.querySelectorAll(".flow-expand"));
  const flowRoutes = Array.from(document.querySelectorAll(".flow-route"));
  const policyActionToggles = Array.from(document.querySelectorAll("[data-policy-actions-toggle]"));
  const fxRankToggles = Array.from(document.querySelectorAll("[data-fx-rank-toggle]"));
  let activeFlowDetail = null;
  let activeFlowRouteKey = null;
  const defaultOhlcKey = "US_10Y";
  const head = document.getElementById("ohlc-head");
  const svg = document.getElementById("ohlc-chart");
  const tooltip = document.getElementById("ohlc-tooltip");
  const panel = document.getElementById("ohlc-panel");
  const rangeLabel = document.getElementById("ohlc-range-label");
  const modeButtons = Array.from(document.querySelectorAll(".ohlc-mode"));
  const windowButtons = Array.from(document.querySelectorAll(".ohlc-window"));
  const zoomInButton = document.getElementById("ohlc-zoom-in");
  const zoomOutButton = document.getElementById("ohlc-zoom-out");
  const resetButton = document.getElementById("ohlc-reset");
  const windowSteps = [90, 180, 360];
  let currentKey = null;
  let chartMode = "move";
  let visibleWindow = 90;
  const viewEndByKey = {};
  let dragStart = null;

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

  const signed = (value, digits = 4) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return "缺失";
    return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}`;
  };

  const pctLabel = (value, digits = 2) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return "缺失";
    if (Math.abs(number) < 0.005) return "0.00%";
    return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}%`;
  };

  const precise = (value, digits = 8) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return "缺失";
    return number.toFixed(digits);
  };

  const qName = (base, quote) => `Q(${base}${quote})`;

  const flowDirectRows = (period) => {
    const result = period?.result || {};
    return (result.direct_rows || []).map((row, index) => ({
      ...row,
      sourceKey: period.changes?.[index]?.source_key || "",
      baseDate: period.changes?.[index]?.base_date || "",
      latestDate: period.changes?.[index]?.latest_date || ""
    }));
  };

  const directTerm = (period, base, quote) => {
    const rows = flowDirectRows(period);
    const direct = rows.find((row) => row.base === base && row.quote === quote);
    if (direct) {
      return {
        base,
        quote,
        value: Number(direct.q),
        direct,
        reversed: false,
        expression: qName(base, quote)
      };
    }
    const reverse = rows.find((row) => row.base === quote && row.quote === base);
    if (reverse) {
      return {
        base,
        quote,
        value: -Number(reverse.q),
        direct: reverse,
        reversed: true,
        expression: `-${qName(reverse.base, reverse.quote)}`
      };
    }
    return null;
  };

  const renderTerm = (term) => {
    if (!term) return '<p class="muted">缺少这一段直接或反向报价。</p>';
    const row = term.direct;
    const rule = term.reversed
      ? `${qName(term.base, term.quote)} = -${qName(row.base, row.quote)} = ${signed(term.value)}`
      : `${qName(term.base, term.quote)} = 100 * ln(${fmt(row.new)} / ${fmt(row.old)}) = ${signed(term.value)}`;
    return `<p class="formula-line">${esc(rule)}</p>`
      + `<p class="muted">${esc(row.sourceKey)}：${esc(row.baseDate)} ${fmt(row.old)} -> ${esc(row.latestDate)} ${fmt(row.new)}</p>`;
  };

  const renderCalculationRows = (term, label) => {
    if (!term) return "";
    const row = term.direct;
    const oldValue = Number(row.old);
    const newValue = Number(row.new);
    const ratio = newValue / oldValue;
    const logValue = Math.log(ratio);
    const directQ = 100 * logValue;
    const targetQ = term.reversed ? -directQ : directQ;
    const reverseRule = term.reversed ? `${qName(term.base, term.quote)} = -${qName(row.base, row.quote)}` : qName(term.base, term.quote);
    return `<tr><td rowspan="5">${esc(label)}<br><span class="muted">${esc(reverseRule)}</span></td><td>old</td><td>${fmt(oldValue)}</td></tr>`
      + `<tr><td>new</td><td>${fmt(newValue)}</td></tr>`
      + `<tr><td>new / old</td><td>${fmt(newValue)} / ${fmt(oldValue)} = ${precise(ratio)}</td></tr>`
      + `<tr><td>ln(new / old)</td><td>ln(${precise(ratio)}) = ${precise(logValue)}</td></tr>`
      + `<tr><td>100 * ln(new / old)</td><td>${signed(directQ)}${term.reversed ? `；反向后 ${signed(targetQ)}` : ""}</td></tr>`;
  };

  const renderCalculationDetails = (first, second, computed) => {
    const firstValue = first?.value || 0;
    const secondValue = second?.value || 0;
    return `<div class="flow-calc-more" hidden>`
      + `<table class="flow-detail-table"><thead><tr><th>段</th><th>步骤</th><th>数字计算</th></tr></thead><tbody>`
      + renderCalculationRows(first, "第一段")
      + renderCalculationRows(second, "第二段")
      + `<tr><td>合成</td><td>score</td><td>${signed(firstValue)} + ${signed(secondValue)} = ${signed(computed)}</td></tr>`
      + `</tbody></table>`
      + `</div>`;
  };

  const createFlowDetail = () => {
    const detail = document.createElement("div");
    detail.className = "flow-route-detail";
    detail.hidden = true;
    const body = document.createElement("div");
    body.className = "flow-detail-body";
    detail.appendChild(body);
    return detail;
  };

  const collapseFlowDetail = () => {
    if (activeFlowDetail) activeFlowDetail.hidden = true;
    activeFlowRouteKey = null;
    flowRoutes.forEach((button) => button.classList.remove("selected"));
  };

  const toggleFlowCalculation = (button) => {
    const target = button.nextElementSibling;
    if (!target || !target.classList.contains("flow-calc-more")) return;
    const nextExpanded = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(nextExpanded));
    target.hidden = !nextExpanded;
    button.textContent = nextExpanded ? "收起数字计算" : "展开数字计算";
  };

  const renderFlowDetail = (sectionIndex, periodIndex, routeIndex, routeButton) => {
    const section = flowData[Number(sectionIndex)];
    const period = section?.periods?.[Number(periodIndex)];
    const route = period?.result?.routes?.[Number(routeIndex)];
    const selectedButton = routeButton || document.querySelector(
      `.flow-route[data-flow-section="${sectionIndex}"][data-flow-period="${periodIndex}"][data-flow-route="${routeIndex}"]`
    );
    if (!section || !period || !route || !selectedButton) return;
    const flowDetail = activeFlowDetail || createFlowDetail();
    const routeKey = `${sectionIndex}-${periodIndex}-${routeIndex}`;
    if (activeFlowRouteKey === routeKey && selectedButton.nextElementSibling === flowDetail && !flowDetail.hidden) {
      collapseFlowDetail();
      return;
    }
    activeFlowRouteKey = routeKey;
    activeFlowDetail = flowDetail;
    const flowDetailBody = flowDetail.querySelector(".flow-detail-body");
    if (!flowDetailBody) return;
    const first = directTerm(period, route.x, route.y);
    const second = directTerm(period, route.y, route.z);
    const computed = (first?.value || 0) + (second?.value || 0);
    const ranking = (period.result?.routes || [])
      .map((item) => `<tr><td>${esc(item.label)}</td><td class="${item.score >= 0 ? "pos" : "neg"}">${signed(item.score)}</td><td>${esc(item.status)}</td></tr>`)
      .join("");
    const directRows = flowDirectRows(period)
      .map((row) => `<tr><td>${esc(row.base)}兑${esc(row.quote)}</td><td>${fmt(row.old)}</td><td>${fmt(row.new)}</td><td class="${row.q >= 0 ? "pos" : "neg"}">${signed(row.q)}</td></tr>`)
      .join("");
    const residuals = (period.result?.triangle_residuals || [])
      .map((item) => `<p class="formula-line">${esc(item.formula)} = ${signed(item.residual)} · ${esc(item.status)}</p>`)
      .join("") || '<p class="muted">无闭环残差。</p>';

    flowRoutes.forEach((button) => {
      const selected = button.dataset.flowSection === String(sectionIndex)
        && button.dataset.flowPeriod === String(periodIndex)
        && button.dataset.flowRoute === String(routeIndex);
      button.classList.toggle("selected", selected);
    });

    flowDetailBody.classList.remove("muted");
    selectedButton.insertAdjacentElement("afterend", flowDetail);
    flowDetail.hidden = false;
    flowDetailBody.innerHTML = `<div class="flow-detail-grid">`
      + `<div class="flow-detail-card">`
      + `<h4>${esc(section.name)}｜${esc(period.period)}｜${esc(route.label)}</h4>`
      + `<p class="formula-line">score = ${qName(route.x, route.y)} + ${qName(route.y, route.z)}</p>`
      + renderTerm(first)
      + renderTerm(second)
      + `<p class="formula-line">score = ${signed(first?.value || 0)} + ${signed(second?.value || 0)} = <strong class="${computed >= 0 ? "pos" : "neg"}">${signed(computed)}</strong></p>`
      + `<p>判定：<strong>${esc(route.status)}</strong>。score &gt; 0 为成立，score &lt; 0 为不成立。</p>`
      + `<button type="button" class="flow-calc-toggle" aria-expanded="false">展开数字计算</button>`
      + renderCalculationDetails(first, second, computed)
      + `</div>`
      + `<div class="flow-detail-card">`
      + `<h4>原始 Q 值</h4>`
      + `<table class="flow-detail-table"><thead><tr><th>货币对</th><th>old</th><th>new</th><th>Q</th></tr></thead><tbody>${directRows}</tbody></table>`
      + `</div>`
      + `<div class="flow-detail-card">`
      + `<h4>同组路线排序</h4>`
      + `<table class="flow-detail-table"><thead><tr><th>路线</th><th>score</th><th>状态</th></tr></thead><tbody>${ranking}</tbody></table>`
      + `</div>`
      + `<div class="flow-detail-card">`
      + `<h4>三角闭环检查</h4>${residuals}`
      + `</div>`
      + `</div>`;
    const calculationToggle = flowDetailBody.querySelector(".flow-calc-toggle");
    calculationToggle?.addEventListener("click", () => toggleFlowCalculation(calculationToggle));
  };

  const toggleFlowRoutes = (button) => {
    const key = `${button.dataset.flowSection}-${button.dataset.flowPeriod}`;
    const routes = document.querySelector(`[data-flow-routes="${key}"]`);
    if (!routes) return;
    const nextExpanded = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(nextExpanded));
    routes.hidden = !nextExpanded;
    const icon = button.querySelector(".toggle-icon");
    if (icon) icon.textContent = nextExpanded ? "▾" : "▸";
    const label = button.querySelector("span:last-child");
    if (label) label.textContent = nextExpanded ? "收起6条路线" : "查看6条路线";
  };

  const yTicks = (min, max, count = 5) => {
    if (min === max) return [min];
    const ticks = [];
    for (let i = 0; i < count; i += 1) {
      ticks.push(min + (max - min) * i / (count - 1));
    }
    return ticks;
  };

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  const sourceRows = (item) => item?.chartType === "bond_curve"
    ? (item.curve?.rows || [])
    : (item.ohlc || []);

  const viewRange = (key, item) => {
    const allRows = sourceRows(item);
    const total = allRows.length;
    if (!total) {
      return { start: 0, end: 0, rows: [], total };
    }
    const size = Math.min(visibleWindow, total);
    const end = clamp(viewEndByKey[key] || total, size, total);
    const start = Math.max(0, end - size);
    viewEndByKey[key] = end;
    return { start, end, rows: allRows.slice(start, end), total };
  };

  const visibleItem = (key, item) => {
    const range = viewRange(key, item);
    if (item.chartType === "bond_curve") {
      return {
        ...item,
        curve: { ...(item.curve || {}), rows: range.rows },
        range
      };
    }
    return { ...item, ohlc: range.rows, range };
  };

  const updateControls = (item) => {
    modeButtons.forEach((button) => {
      button.classList.toggle("active", button.dataset.mode === chartMode);
    });
    windowButtons.forEach((button) => {
      button.classList.toggle("active", Number(button.dataset.window) === visibleWindow);
    });
    const range = item?.range;
    if (!rangeLabel || !range) return;
    if (!range.total) {
      rangeLabel.textContent = "无可用日线";
      return;
    }
    const first = range.rows[0]?.date || "";
    const last = range.rows[range.rows.length - 1]?.date || "";
    rangeLabel.textContent = `${first} 到 ${last} · ${range.rows.length}/${range.total}`;
  };

  const rerenderCurrent = () => {
    if (currentKey) render(currentKey, { scroll: false });
  };

  const setVisibleWindow = (nextWindow) => {
    visibleWindow = clamp(Number(nextWindow), windowSteps[0], windowSteps[windowSteps.length - 1]);
    rerenderCurrent();
  };

  const zoomChart = (direction) => {
    const index = windowSteps.indexOf(visibleWindow);
    const nextIndex = clamp(index + direction, 0, windowSteps.length - 1);
    setVisibleWindow(windowSteps[nextIndex]);
  };

  const renderMoveChart = (item) => {
    const bars = item.ohlc || [];
    const width = 980;
    const height = 360;
    const margin = { left: 64, right: 22, top: 22, bottom: 58 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;
    tooltip.classList.add("dark");
    if (!bars.length) {
      svg.innerHTML = `<text x="490" y="180" text-anchor="middle" fill="#66717d">没有日线涨跌幅数据</text>`;
      return;
    }
    const moves = bars.map((bar, index) => ({
      bar,
      index,
      value: Number(bar.change_pct)
    })).filter((item) => Number.isFinite(item.value));
    if (!moves.length) {
      svg.innerHTML = `<text x="490" y="180" text-anchor="middle" fill="#66717d">没有可计算的前收盘涨跌幅</text>`;
      return;
    }

    const maxAbs = Math.max(0.1, ...moves.map((move) => Math.abs(move.value))) * 1.16;
    const min = -maxAbs;
    const max = maxAbs;
    const xStep = innerW / Math.max(1, bars.length - 1);
    const x = (index) => bars.length === 1 ? margin.left + innerW / 2 : margin.left + index * xStep;
    const y = (value) => margin.top + (max - Number(value)) / (max - min) * innerH;
    const zeroY = y(0);
    const barW = Math.max(2, Math.min(8, xStep * 0.42));
    const linePath = moves.map((move, pathIndex) => `${pathIndex === 0 ? "M" : "L"} ${x(move.index).toFixed(2)} ${y(move.value).toFixed(2)}`).join(" ");
    const labelCount = Math.min(24, Math.max(8, Math.round(moves.length / 4)));
    const labelThreshold = [...moves]
      .map((move) => Math.abs(move.value))
      .sort((a, b) => b - a)[labelCount - 1] || Infinity;

    const grid = yTicks(min, max, 7).map((tick) => {
      const yy = y(tick);
      const zero = Math.abs(tick) < 0.00001;
      return `<line x1="${margin.left}" x2="${width - margin.right}" y1="${yy}" y2="${yy}" stroke="${zero ? "#b8c1cc" : "#edf1f5"}" stroke-width="${zero ? 1.4 : 1}" />`
        + `<text x="${margin.left - 10}" y="${yy + 4}" text-anchor="end" fill="#66717d" font-size="11">${zero ? "0%" : pctLabel(tick)}</text>`;
    }).join("");

    const dateTicks = [];
    const tickCount = Math.min(10, bars.length);
    for (let i = 0; i < tickCount; i += 1) {
      const index = Math.round(i * (bars.length - 1) / Math.max(1, tickCount - 1));
      const xx = x(index);
      dateTicks.push(`<text x="${xx}" y="${height - 16}" transform="rotate(-48 ${xx} ${height - 16})" text-anchor="end" fill="#66717d" font-size="10">${esc(bars[index].date.slice(5))}</text>`);
    }

    const moveBars = moves.map((move) => {
      const xx = x(move.index);
      const yy = y(move.value);
      const positive = move.value >= 0;
      const color = positive ? "#3b82f6" : "#ff5b8a";
      const rectY = Math.min(zeroY, yy);
      const rectH = Math.max(1.2, Math.abs(zeroY - yy));
      return `<rect x="${xx - barW / 2}" y="${rectY}" width="${barW}" height="${rectH}" rx="1" fill="${color}" opacity="0.84" />`;
    }).join("");

    const dots = moves.map((move) => {
      const xx = x(move.index);
      const yy = y(move.value);
      const showLabel = Math.abs(move.value) >= labelThreshold && Math.abs(move.value) >= maxAbs * 0.18;
      const labelY = yy + (move.value >= 0 ? -8 : 15);
      const label = showLabel
        ? `<text x="${xx}" y="${labelY}" text-anchor="middle" fill="#f2a51a" font-size="9" font-weight="650">${pctLabel(move.value)}</text>`
        : "";
      return `<circle cx="${xx}" cy="${yy}" r="2.4" fill="#f4b43f" stroke="#fff" stroke-width="0.8" />${label}`;
    }).join("");

    const hitW = Math.max(8, xStep);
    const hits = bars.map((bar, index) => (
      `<g class="move-hit" data-index="${index}">`
      + `<line class="move-crosshair" x1="${x(index)}" x2="${x(index)}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#98a2b3" stroke-width="1" opacity="0" />`
      + `<rect x="${x(index) - hitW / 2}" y="${margin.top}" width="${hitW}" height="${innerH}" fill="transparent" />`
      + `</g>`
    )).join("");

    svg.innerHTML = `<rect width="${width}" height="${height}" fill="#fff" />`
      + grid
      + `<line x1="${margin.left}" x2="${margin.left}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#d5dbe3" />`
      + `<line x1="${margin.left}" x2="${width - margin.right}" y1="${height - margin.bottom}" y2="${height - margin.bottom}" stroke="#d5dbe3" />`
      + dateTicks.join("")
      + moveBars
      + `<path d="${linePath}" fill="none" stroke="#f4b43f" stroke-width="1.8" />`
      + dots
      + hits;

    Array.from(svg.querySelectorAll(".move-hit")).forEach((node) => {
      const bar = bars[Number(node.dataset.index)];
      const change = Number(bar.change_pct);
      node.addEventListener("mousemove", (event) => {
        Array.from(svg.querySelectorAll(".move-crosshair")).forEach((line) => { line.setAttribute("opacity", "0"); });
        const crosshair = node.querySelector(".move-crosshair");
        if (crosshair) crosshair.setAttribute("opacity", "1");
        const bounds = panel.getBoundingClientRect();
        tooltip.classList.add("dark");
        tooltip.style.display = "block";
        tooltip.style.left = `${Math.min(bounds.width - 236, Math.max(8, event.clientX - bounds.left + 14))}px`;
        tooltip.style.top = `${Math.max(8, event.clientY - bounds.top - 96)}px`;
        const moveText = Number.isFinite(change) ? pctLabel(change) : "缺失";
        tooltip.innerHTML = `<strong>${esc(bar.date)}</strong>`
          + `<div>${esc(item.country)} ${esc(item.label)} 涨跌幅：<b>${moveText}</b></div>`
          + `<div class="muted">Prev close: ${fmt(bar.prev_close)}</div>`
          + `<div>Open: ${fmt(bar.open)} · High: ${fmt(bar.high)}</div>`
          + `<div>Low: ${fmt(bar.low)} · Close: ${fmt(bar.close)}</div>`;
      });
      node.addEventListener("mouseleave", () => {
        const crosshair = node.querySelector(".move-crosshair");
        if (crosshair) crosshair.setAttribute("opacity", "0");
        tooltip.style.display = "none";
      });
    });
  };

  const renderChart = (item) => {
    const bars = item.ohlc || [];
    const width = 980;
    const height = 360;
    const margin = { left: 64, right: 22, top: 22, bottom: 38 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;
    tooltip.classList.remove("dark");
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
    tooltip.classList.remove("dark");
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

  const render = (key, options = {}) => {
    const sourceItem = ohlcData[key];
    if (!sourceItem) return;
    const { scroll = true } = options;
    currentKey = key;
    const item = visibleItem(key, sourceItem);
    rows.forEach((row) => row.classList.toggle("selected", row.dataset.ohlcKey === key));
    if (item.chartType === "bond_curve") {
      const count = item.curve?.rows?.length || 0;
      const total = item.range?.total || count;
      head.textContent = `${item.country} / 债券曲线：2Y 与 10Y 显示 ${count}/${total} 条日线 close；绿色为 10Y > 2Y，红色为 10Y < 2Y。`;
      renderBondCurveChart(item);
    } else {
      const total = item.range?.total || item.ohlc.length;
      if (chartMode === "move") {
        head.textContent = `${item.country} / ${item.group} / ${item.label}：涨跌幅模式，显示 ${item.ohlc.length}/${total} 条日线；柱=单日涨跌幅，橙线=同一涨跌幅序列，悬停看 OHLC。`;
        renderMoveChart(item);
      } else {
        head.textContent = `${item.country} / ${item.group} / ${item.label}：K线模式，显示 ${item.ohlc.length}/${total} 条日线，鼠标悬停显示 OHLC；拖动图表可平移。`;
        renderChart(item);
      }
    }
    updateControls(item);
    if (scroll) {
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  rows.forEach((row) => {
    row.addEventListener("click", () => render(row.dataset.ohlcKey));
  });

  flowExpandButtons.forEach((button) => {
    button.addEventListener("click", () => toggleFlowRoutes(button));
  });

  flowRoutes.forEach((button) => {
    button.addEventListener("click", () => {
      renderFlowDetail(button.dataset.flowSection, button.dataset.flowPeriod, button.dataset.flowRoute, button);
    });
  });

  const toggleCountryRows = (button) => {
    const country = button.dataset.country;
    const nextExpanded = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(nextExpanded));
    button.classList.toggle("expanded", nextExpanded);
    button.classList.toggle("collapsed", !nextExpanded);
    const icon = button.querySelector(".toggle-icon");
    if (icon) icon.textContent = nextExpanded ? "▾" : "▸";
    rows.forEach((row) => {
      if (row.dataset.country === country) {
        row.hidden = !nextExpanded;
      }
    });
  };

  countryToggles.forEach((button) => {
    button.addEventListener("click", () => toggleCountryRows(button));
  });

  policyActionToggles.forEach((button) => {
    button.addEventListener("click", () => {
      const code = button.getAttribute("data-policy-actions-toggle");
      const panel = document.querySelector(`[data-policy-actions-expanded="${code}"]`);
      if (!panel) return;
      const nextHidden = !panel.hidden;
      panel.hidden = nextHidden;
      button.textContent = nextHidden ? "查看近一年实际操作" : "收起近一年实际操作";
    });
  });

  fxRankToggles.forEach((button) => {
    button.addEventListener("click", () => {
      const code = button.getAttribute("data-fx-rank-toggle");
      const detail = document.querySelector('[data-fx-rank-detail="' + code + '"]');
      if (!detail) return;
      const nextExpanded = button.getAttribute("aria-expanded") !== "true";
      fxRankToggles.forEach((otherButton) => {
        const otherCode = otherButton.getAttribute("data-fx-rank-toggle");
        const otherDetail = document.querySelector('[data-fx-rank-detail="' + otherCode + '"]');
        otherButton.setAttribute("aria-expanded", "false");
        const otherIcon = otherButton.querySelector(".toggle-icon");
        if (otherIcon) otherIcon.textContent = "▸";
        if (otherDetail) otherDetail.hidden = true;
      });
      button.setAttribute("aria-expanded", String(nextExpanded));
      detail.hidden = !nextExpanded;
      const icon = button.querySelector(".toggle-icon");
      if (icon) icon.textContent = nextExpanded ? "▾" : "▸";
    });
  });

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      chartMode = button.dataset.mode || "move";
      rerenderCurrent();
    });
  });

  windowButtons.forEach((button) => {
    button.addEventListener("click", () => setVisibleWindow(Number(button.dataset.window)));
  });
  zoomInButton?.addEventListener("click", () => zoomChart(-1));
  zoomOutButton?.addEventListener("click", () => zoomChart(1));
  resetButton?.addEventListener("click", () => {
    if (!currentKey) return;
    viewEndByKey[currentKey] = sourceRows(ohlcData[currentKey]).length;
    visibleWindow = 90;
    render(currentKey, { scroll: false });
  });

  svg.addEventListener("mousedown", (event) => {
    if (!currentKey) return;
    const source = sourceRows(ohlcData[currentKey]);
    if (source.length <= visibleWindow) return;
    dragStart = {
      x: event.clientX,
      end: viewEndByKey[currentKey] || source.length
    };
    svg.classList.add("dragging");
    tooltip.style.display = "none";
    event.preventDefault();
  });

  window.addEventListener("mousemove", (event) => {
    if (!dragStart || !currentKey) return;
    const source = sourceRows(ohlcData[currentKey]);
    const size = Math.min(visibleWindow, source.length);
    const bounds = svg.getBoundingClientRect();
    const pixelsPerBar = bounds.width / Math.max(1, size);
    const deltaBars = Math.round((dragStart.x - event.clientX) / pixelsPerBar);
    viewEndByKey[currentKey] = clamp(dragStart.end + deltaBars, size, source.length);
    render(currentKey, { scroll: false });
  });

  window.addEventListener("mouseup", () => {
    dragStart = null;
    svg.classList.remove("dragging");
  });
  render(defaultOhlcKey, { scroll: false });
})();
"""


def main() -> int:
    args = parse_args()
    fetch_records = fetch_all(args) if args.fetch else []
    snapshot = build_snapshot(fetch_records, fetch_policy_news=args.fetch)
    DASHBOARD.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_JSON.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    HTML_OUT.write_text(render_html(snapshot), encoding="utf-8")
    print(f"wrote {HTML_OUT}")
    print(f"wrote {SNAPSHOT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
