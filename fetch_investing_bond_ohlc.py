#!/usr/bin/env python3
"""Fetch bond yield OHLC history from Investing.com historical tables."""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
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

    @property
    def page_url(self) -> str:
        return f"{BASE_URL}/{self.path_prefix}/{self.slug}"


BOND_SPECS = {
    "DE2Y": BondSpec(
        key="DE2Y",
        instrument_id="23685",
        source_symbol="DE2YT=RR",
        slug="germany-2-year-bond-yield-historical-data",
        header="Germany 2-Year Bond Yield Historical Data",
        output_name="DE2YR_INVESTING_1D_ohlc.csv",
    ),
    "DE10Y": BondSpec(
        key="DE10Y",
        instrument_id="23693",
        source_symbol="DE10YT=RR",
        slug="germany-10-year-bond-yield-historical-data",
        header="Germany 10-Year Bond Yield Historical Data",
        output_name="DE10YR_INVESTING_1D_ohlc.csv",
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
    "JP10Y": BondSpec(
        key="JP10Y",
        instrument_id="23901",
        source_symbol="JP10YT=RR",
        slug="japan-10-year-bond-yield-historical-data",
        header="Japan 10-Year Bond Yield Historical Data",
        output_name="JP10YR_INVESTING_1D_ohlc.csv",
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
    "KR2Y": BondSpec(
        key="KR2Y",
        instrument_id="29295",
        source_symbol="KR2YT=RR",
        slug="south-korea-2-year-bond-yield-historical-data",
        header="South Korea 2-Year Bond Yield Historical Data",
        output_name="KR2YR_INVESTING_1D_ohlc.csv",
    ),
    "KR10Y": BondSpec(
        key="KR10Y",
        instrument_id="29292",
        source_symbol="KR10YT=RR",
        slug="south-korea-10-year-bond-yield-historical-data",
        header="South Korea 10-Year Bond Yield Historical Data",
        output_name="KR10YR_INVESTING_1D_ohlc.csv",
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
    opener.open(Request(spec.page_url, headers=make_headers()), timeout=30).read()

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

    return [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)]


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
