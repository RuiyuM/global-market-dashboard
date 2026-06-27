#!/usr/bin/env python3
"""Fetch Japan government bond yield rows from server-safe sources."""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from io import StringIO
from typing import Any
from urllib.request import Request, urlopen


MOF_HISTORICAL_CSV_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
TRADINGECONOMICS_BASE_URL = "https://tradingeconomics.com/japan"

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


def row_from_tradingeconomics_quote_html(html: str) -> dict[str, Any] | None:
    match = re.search(
        r"The yield on.*?(?:rose|eased|fell|declined|increased|decreased|held steady|was)\s+(?:(?:to|at)\s+)?(-?\d+(?:\.\d+)?)%\s+on\s+([A-Z][a-z]+ \d{1,2}, \d{4})",
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
