#!/usr/bin/env python3
"""Fetch bond yield OHLC history from Investing.com historical tables."""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
import http.cookiejar


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORICAL_URL = "https://www.investing.com/instruments/HistoricalDataAjax"
BASE_URL = "https://www.investing.com"


@dataclass(frozen=True)
class BondSpec:
    key: str
    instrument_id: str
    source_symbol: str
    slug: str
    header: str
    output_name: str
    path_prefix: str = "rates-bonds"
    fetch_mode: str = "ajax"

    @property
    def page_url(self) -> str:
        return f"{BASE_URL}/{self.path_prefix}/{self.slug}"


BOND_SPECS = {
    "JP1M": BondSpec(
        key="JP1M",
        instrument_id="208090",
        source_symbol="JP1MT=XX",
        slug="japan-1-month-historical-data",
        header="Japan 1-Month Bond Yield Historical Data",
        output_name="JP1M_INVESTING_1D_ohlc.csv",
        fetch_mode="page",
    ),
    "JP3M": BondSpec(
        key="JP3M",
        instrument_id="23890",
        source_symbol="JP3MT=XX",
        slug="japan-3-month-bond-yield-historical-data",
        header="Japan 3-Month Bond Yield Historical Data",
        output_name="JP3M_INVESTING_1D_ohlc.csv",
    ),
    "JP6M": BondSpec(
        key="JP6M",
        instrument_id="23891",
        source_symbol="JP6MT=XX",
        slug="japan-6-month-bond-yield-historical-data",
        header="Japan 6-Month Bond Yield Historical Data",
        output_name="JP6M_INVESTING_1D_ohlc.csv",
    ),
    "DE2Y": BondSpec(
        key="DE2Y",
        instrument_id="23685",
        source_symbol="DE2YT=RR",
        slug="germany-2-year-bond-yield-historical-data",
        header="Germany 2-Year Bond Yield Historical Data",
        output_name="DE2YR_INVESTING_1D_ohlc.csv",
    ),
    "DE3M": BondSpec(
        key="DE3M",
        instrument_id="23681",
        source_symbol="DE3MT=RR",
        slug="germany-3-month-bond-yield-historical-data",
        header="Germany 3-Month Bond Yield Historical Data",
        output_name="DE3MR_INVESTING_1D_ohlc.csv",
    ),
    "DE6M": BondSpec(
        key="DE6M",
        instrument_id="23682",
        source_symbol="DE6MT=RR",
        slug="germany-6-month-bond-yield-historical-data",
        header="Germany 6-Month Bond Yield Historical Data",
        output_name="DE6MR_INVESTING_1D_ohlc.csv",
    ),
    "DE1Y": BondSpec(
        key="DE1Y",
        instrument_id="23684",
        source_symbol="DE1YT=RR",
        slug="germany-1-year-bond-yield-historical-data",
        header="Germany 1-Year Bond Yield Historical Data",
        output_name="DE1YR_INVESTING_1D_ohlc.csv",
    ),
    "DE3Y": BondSpec(
        key="DE3Y",
        instrument_id="23686",
        source_symbol="DE3YT=RR",
        slug="germany-3-year-bond-yield-historical-data",
        header="Germany 3-Year Bond Yield Historical Data",
        output_name="DE3YR_INVESTING_1D_ohlc.csv",
    ),
    "DE5Y": BondSpec(
        key="DE5Y",
        instrument_id="23688",
        source_symbol="DE5YT=RR",
        slug="germany-5-year-bond-yield-historical-data",
        header="Germany 5-Year Bond Yield Historical Data",
        output_name="DE5YR_INVESTING_1D_ohlc.csv",
    ),
    "DE7Y": BondSpec(
        key="DE7Y",
        instrument_id="23690",
        source_symbol="DE7YT=RR",
        slug="germany-7-year-bond-yield-historical-data",
        header="Germany 7-Year Bond Yield Historical Data",
        output_name="DE7YR_INVESTING_1D_ohlc.csv",
    ),
    "DE10Y": BondSpec(
        key="DE10Y",
        instrument_id="23693",
        source_symbol="DE10YT=RR",
        slug="germany-10-year-bond-yield-historical-data",
        header="Germany 10-Year Bond Yield Historical Data",
        output_name="DE10YR_INVESTING_1D_ohlc.csv",
    ),
    "DE30Y": BondSpec(
        key="DE30Y",
        instrument_id="23696",
        source_symbol="DE30YT=RR",
        slug="germany-30-year-bond-yield-historical-data",
        header="Germany 30-Year Bond Yield Historical Data",
        output_name="DE30YR_INVESTING_1D_ohlc.csv",
    ),
    "JP1Y": BondSpec(
        key="JP1Y",
        instrument_id="23892",
        source_symbol="JP1YT=XX",
        slug="japan-1-year-bond-yield-historical-data",
        header="Japan 1-Year Bond Yield Historical Data",
        output_name="JP1YR_INVESTING_1D_ohlc.csv",
    ),
    "JP2Y": BondSpec(
        key="JP2Y",
        instrument_id="23893",
        source_symbol="JP2YT=XX",
        slug="japan-2-year-bond-yield-historical-data",
        header="Japan 2-Year Bond Yield Historical Data",
        output_name="JP2YR_INVESTING_1D_ohlc.csv",
    ),
    "JP3Y": BondSpec(
        key="JP3Y",
        instrument_id="23894",
        source_symbol="JP3YT=XX",
        slug="japan-3-year-bond-yield-historical-data",
        header="Japan 3-Year Bond Yield Historical Data",
        output_name="JP3YR_INVESTING_1D_ohlc.csv",
    ),
    "JP5Y": BondSpec(
        key="JP5Y",
        instrument_id="23896",
        source_symbol="JP5YT=XX",
        slug="japan-5-year-bond-yield-historical-data",
        header="Japan 5-Year Bond Yield Historical Data",
        output_name="JP5YR_INVESTING_1D_ohlc.csv",
    ),
    "JP7Y": BondSpec(
        key="JP7Y",
        instrument_id="23898",
        source_symbol="JP7YT=XX",
        slug="japan-7-year-bond-yield-historical-data",
        header="Japan 7-Year Bond Yield Historical Data",
        output_name="JP7YR_INVESTING_1D_ohlc.csv",
    ),
    "JP10Y": BondSpec(
        key="JP10Y",
        instrument_id="23901",
        source_symbol="JP10YT=RR",
        slug="japan-10-year-bond-yield-historical-data",
        header="Japan 10-Year Bond Yield Historical Data",
        output_name="JP10YR_INVESTING_1D_ohlc.csv",
    ),
    "JP30Y": BondSpec(
        key="JP30Y",
        instrument_id="23904",
        source_symbol="JP30YT=XX",
        slug="japan-30-year-bond-yield-historical-data",
        header="Japan 30-Year Bond Yield Historical Data",
        output_name="JP30YR_INVESTING_1D_ohlc.csv",
    ),
    "RU2Y": BondSpec(
        key="RU2Y",
        instrument_id="23971",
        source_symbol="RU2YT=RR",
        slug="russia-2-year-bond-yield-historical-data",
        header="Russia 2-Year Bond Yield Historical Data",
        output_name="RU2YR_INVESTING_1D_ohlc.csv",
    ),
    "RU10Y": BondSpec(
        key="RU10Y",
        instrument_id="23974",
        source_symbol="RU10YT=RR",
        slug="russia-10-year-bond-yield-historical-data",
        header="Russia 10-Year Bond Yield Historical Data",
        output_name="RU10YR_INVESTING_1D_ohlc.csv",
    ),
    "KR1Y": BondSpec(
        key="KR1Y",
        instrument_id="29294",
        source_symbol="KR1YT=RR",
        slug="south-korea-1-year-bond-yield-historical-data",
        header="South Korea 1-Year Bond Yield Historical Data",
        output_name="KR1YR_INVESTING_1D_ohlc.csv",
    ),
    "KR2Y": BondSpec(
        key="KR2Y",
        instrument_id="29295",
        source_symbol="KR2YT=RR",
        slug="south-korea-2-year-bond-yield-historical-data",
        header="South Korea 2-Year Bond Yield Historical Data",
        output_name="KR2YR_INVESTING_1D_ohlc.csv",
    ),
    "KR3Y": BondSpec(
        key="KR3Y",
        instrument_id="29296",
        source_symbol="KR3YT=RR",
        slug="south-korea-3-year-bond-yield-historical-data",
        header="South Korea 3-Year Bond Yield Historical Data",
        output_name="KR3YR_INVESTING_1D_ohlc.csv",
    ),
    "KR5Y": BondSpec(
        key="KR5Y",
        instrument_id="29298",
        source_symbol="KR5YT=RR",
        slug="south-korea-5-year-bond-yield-historical-data",
        header="South Korea 5-Year Bond Yield Historical Data",
        output_name="KR5YR_INVESTING_1D_ohlc.csv",
    ),
    "KR10Y": BondSpec(
        key="KR10Y",
        instrument_id="29292",
        source_symbol="KR10YT=RR",
        slug="south-korea-10-year-bond-yield-historical-data",
        header="South Korea 10-Year Bond Yield Historical Data",
        output_name="KR10YR_INVESTING_1D_ohlc.csv",
    ),
    "KR30Y": BondSpec(
        key="KR30Y",
        instrument_id="1052525",
        source_symbol="KR30YT=RR",
        slug="south-korea-30-year-historical-data",
        header="South Korea 30-Year Bond Yield Historical Data",
        output_name="KR30YR_INVESTING_1D_ohlc.csv",
    ),
    "RU_EQUITY": BondSpec(
        key="RU_EQUITY",
        instrument_id="13666",
        source_symbol="IMOEX",
        slug="mcx-historical-data",
        header="MOEX Russia Index Historical Data",
        output_name="RU_EQUITY_INVESTING_1D_ohlc.csv",
        path_prefix="indices",
    ),
}


class InvestingHistoricalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict[str, str]]] = []
        self._in_row = False
        self._in_td = False
        self._current_row: list[dict[str, str]] = []
        self._current_td: dict[str, str] = {}
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag == "td":
            attr_map = {key: value or "" for key, value in attrs}
            self._in_td = True
            self._current_td = {"real": attr_map.get("data-real-value", "")}
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_td:
            self._current_td["text"] = " ".join("".join(self._text_parts).split())
            self._current_row.append(self._current_td)
            self._in_td = False
        elif tag == "tr" and self._in_row:
            if len(self._current_row) >= 5:
                self.rows.append(self._current_row)
            self._in_row = False


def parse_date_arg(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def investing_date(value: date) -> str:
    return value.strftime("%m/%d/%Y")


def make_headers(referer: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def build_cookie_opener():
    cookie_jar = http.cookiejar.CookieJar()
    return build_opener(HTTPCookieProcessor(cookie_jar))


def fetch_html(spec: BondSpec, start_date: date, end_date: date) -> str:
    opener = build_cookie_opener()
    page_html = opener.open(Request(spec.page_url, headers=make_headers()), timeout=30).read().decode("utf-8", "ignore")
    if spec.fetch_mode == "page":
        return page_html

    form = urlencode(
        {
            "curr_id": spec.instrument_id,
            "smlID": "",
            "header": spec.header,
            "st_date": investing_date(start_date),
            "end_date": investing_date(end_date),
            "interval_sec": "Daily",
            "sort_col": "date",
            "sort_ord": "DESC",
            "action": "historical_data",
        }
    ).encode("utf-8")
    headers = make_headers(spec.page_url)
    headers.update(
        {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    with opener.open(Request(HISTORICAL_URL, data=form, headers=headers), timeout=60) as response:
        return response.read().decode("utf-8", "ignore")


def extract_json_object_after_marker(text: str, marker: str) -> dict[str, object] | None:
    marker_index = text.find(marker)
    if marker_index < 0:
        return None
    start = text.find("{", marker_index + len(marker))
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    return None


def parse_float(value: object) -> float:
    return float(str(value).replace(",", ""))


def rows_from_next_historical_data(html: str) -> list[dict[str, str | int | float]]:
    text = html if '"historicalDataStore"' in html else unescape(html)
    store = extract_json_object_after_marker(text, '"historicalDataStore":')
    if not store:
        return []

    historical = store.get("historicalData")
    if not isinstance(historical, dict):
        return []
    data = historical.get("data")
    if not isinstance(data, list):
        return []

    rows_by_timestamp: dict[int, dict[str, str | int | float]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            timestamp = int(item["rowDateRaw"])
            close = parse_float(item.get("last_closeRaw") or item.get("last_close"))
            open_ = parse_float(item.get("last_openRaw") or item.get("last_open") or close)
            high = parse_float(item.get("last_maxRaw") or item.get("last_max") or close)
            low = parse_float(item.get("last_minRaw") or item.get("last_min") or close)
        except (KeyError, TypeError, ValueError):
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


def rows_from_html(html: str) -> list[dict[str, str | int | float]]:
    parser = InvestingHistoricalParser()
    parser.feed(html)
    rows_by_timestamp: dict[int, dict[str, str | int | float]] = {}

    for cells in parser.rows:
        try:
            timestamp = int(cells[0]["real"])
            close = float(cells[1]["real"].replace(",", ""))
            open_ = float(cells[2]["real"].replace(",", ""))
            high = float(cells[3]["real"].replace(",", ""))
            low = float(cells[4]["real"].replace(",", ""))
        except (ValueError, IndexError):
            continue
        rows_by_timestamp[timestamp] = {
            "date": datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat(),
            "timestamp": timestamp,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
        }

    rows = [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)]
    if rows:
        return rows
    return rows_from_next_historical_data(html)


def write_csv(path: Path, rows: Iterable[dict[str, str | int | float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "timestamp", "open", "high", "low", "close"])
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*", default=sorted(BOND_SPECS))
    parser.add_argument("--start-date", default="2016-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--sleep-sec", type=float, default=0.5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    start_date = parse_date_arg(args.start_date)
    end_date = parse_date_arg(args.end_date)
    if end_date < start_date:
        raise ValueError("--end-date must be on or after --start-date")

    for symbol in args.symbols:
        key = symbol.upper()
        if key not in BOND_SPECS:
            raise ValueError(f"Unsupported symbol {symbol}; choose from {', '.join(sorted(BOND_SPECS))}")
        spec = BOND_SPECS[key]
        html = fetch_html(spec, start_date, end_date)
        rows = rows_from_html(html)
        output_path = args.output_dir / spec.output_name
        write_csv(output_path, rows)
        start = rows[0]["date"] if rows else ""
        end = rows[-1]["date"] if rows else ""
        print(
            f"{key} {spec.source_symbol}: wrote {len(rows)} rows "
            f"{start} -> {end} to {output_path}"
        )
        time.sleep(args.sleep_sec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
