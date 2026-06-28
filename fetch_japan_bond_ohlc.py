#!/usr/bin/env python3
"""Fetch Japan government bond yield rows from server-safe sources."""

from __future__ import annotations

import base64
import csv
import gzip
import json
import re
from datetime import date, datetime, timezone
from io import StringIO
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


MOF_HISTORICAL_CSV_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
TRADINGECONOMICS_BASE_URL = "https://tradingeconomics.com/japan"
TRADINGECONOMICS_CHART_FALLBACK_DATASOURCE = "https://d3ii0wo49og5mi.cloudfront.net"
TRADINGECONOMICS_CHART_OBFUSCATION_KEY = b"tradingeconomics-charts-core-api-key"

TRADINGECONOMICS_SLUGS = {
    "1M": "1-month-bill-yield",
    "3M": "3-month-bill-yield",
    "6M": "6-month-bill-yield",
    "1Y": "52-week-bill-yield",
    "2Y": "2-year-note-yield",
    "3Y": "3-year-note-yield",
    "5Y": "5-year-note-yield",
    "7Y": "7-year-note-yield",
    "10Y": "government-bond-yield",
    "30Y": "30-year-bond-yield",
}


def epoch_for_date(value: datetime) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp())


def close_only_row(date_text: str, close: float) -> dict[str, Any]:
    parsed = datetime.strptime(date_text, "%Y-%m-%d")
    return {
        "date": parsed.date().isoformat(),
        "timestamp": epoch_for_date(parsed),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
    }


def rows_by_tenor_from_mof_csv(csv_text: str) -> dict[str, list[dict[str, Any]]]:
    lines = csv_text.splitlines()
    if len(lines) < 2:
        return {}

    result: dict[str, list[dict[str, Any]]] = {}
    for row in csv.DictReader(StringIO("\n".join(lines[1:]))):
        raw_date = (row.get("Date") or "").strip()
        try:
            parsed_date = datetime.strptime(raw_date, "%Y/%m/%d").date().isoformat()
        except ValueError:
            continue
        for tenor, value in row.items():
            if tenor == "Date" or not value or value == "-":
                continue
            try:
                close = float(value)
            except ValueError:
                continue
            result.setdefault(tenor, []).append(close_only_row(parsed_date, close))
    return result


def fetch_mof_jgb_rows_by_tenor() -> dict[str, list[dict[str, Any]]]:
    request = Request(MOF_HISTORICAL_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    raw = urlopen(request, timeout=60).read().decode("shift_jis", "ignore")
    return rows_by_tenor_from_mof_csv(raw)


def rows_from_tradingeconomics_chart_payload(payload_text: str) -> list[dict[str, Any]]:
    encoded_payload = json.loads(payload_text)
    if not isinstance(encoded_payload, str):
        return []

    compressed = bytearray(base64.b64decode(encoded_payload))
    for index in range(len(compressed)):
        compressed[index] ^= TRADINGECONOMICS_CHART_OBFUSCATION_KEY[index % len(TRADINGECONOMICS_CHART_OBFUSCATION_KEY)]
    payload = json.loads(gzip.decompress(bytes(compressed)).decode("utf-8"))

    rows_by_timestamp: dict[int, dict[str, Any]] = {}
    for series in payload.get("series", []):
        if not isinstance(series, dict):
            continue
        for point in series.get("data", []):
            if not isinstance(point, list) or len(point) < 2:
                continue
            try:
                raw_timestamp = int(point[0])
                timestamp = raw_timestamp // 1000 if raw_timestamp > 10_000_000_000 else raw_timestamp
                close = float(point[7] if len(point) > 7 and point[7] is not None else point[1])
                open_ = float(point[4] if len(point) > 4 and point[4] is not None else close)
                high = float(point[5] if len(point) > 5 and point[5] is not None else close)
                low = float(point[6] if len(point) > 6 and point[6] is not None else close)
            except (TypeError, ValueError):
                continue
            rows_by_timestamp[timestamp] = {
                "date": datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat(),
                "timestamp": timestamp,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
            }
    return [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)]


def extract_assignment(html: str, variable_name: str) -> str | None:
    match = re.search(rf"\b{re.escape(variable_name)}\s*=\s*'([^']+)'", html)
    return match.group(1) if match else None


def fetch_tradingeconomics_chart_rows(slug: str, start_day: date, end_day: date) -> list[dict[str, Any]]:
    page_url = f"{TRADINGECONOMICS_BASE_URL}/{slug}"
    page_request = Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
    html = urlopen(page_request, timeout=30).read().decode("utf-8", "ignore")
    symbol = extract_assignment(html, "symbol")
    if not symbol:
        return []
    data_source = extract_assignment(html, "TEChartsDatasource") or TRADINGECONOMICS_CHART_FALLBACK_DATASOURCE
    api_key = extract_assignment(html, "TEChartsToken")
    url = (
        f"{data_source.rstrip('/')}/markets/{quote(symbol, safe=':')}"
        f"?d1={start_day.isoformat()}&d2={end_day.isoformat()}&interval=1d&ohlc=1"
    )
    headers = {"User-Agent": "Mozilla/5.0", "Referer": page_url}
    if api_key:
        headers["x-api-key"] = api_key
    request = Request(url, headers=headers)
    payload_text = urlopen(request, timeout=60).read().decode("utf-8", "ignore")
    return rows_from_tradingeconomics_chart_payload(payload_text)


def row_from_tradingeconomics_quote_html(html: str) -> dict[str, Any] | None:
    match = re.search(
        r"The yield on.*?(?:rose|eased|fell|declined|increased|decreased|held\s+steady|was)\s+(?:(?:to|at)\s+)?(-?\d+(?:\.\d+)?)%\s+on\s+([A-Z][a-z]+ \d{1,2}, \d{4})",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    close = float(match.group(1))
    parsed = datetime.strptime(match.group(2), "%B %d, %Y")
    return close_only_row(parsed.date().isoformat(), close)


def fetch_tradingeconomics_latest_row(slug: str) -> dict[str, Any] | None:
    request = Request(f"{TRADINGECONOMICS_BASE_URL}/{slug}", headers={"User-Agent": "Mozilla/5.0"})
    html = urlopen(request, timeout=30).read().decode("utf-8", "ignore")
    return row_from_tradingeconomics_quote_html(html)
