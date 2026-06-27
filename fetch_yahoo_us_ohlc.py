#!/usr/bin/env python3
"""Fetch daily OHLCV data for US stocks from Yahoo Finance chart data."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "Mozilla/5.0"
CSV_FIELDS = [
    "date",
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
]


def date_to_epoch(date_text: str) -> int:
    parsed = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def inclusive_end_to_epoch(end_date_text: str) -> int:
    parsed = datetime.strptime(end_date_text, "%Y-%m-%d").date() + timedelta(days=1)
    return int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc).timestamp())


def yahoo_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def build_chart_url(symbol: str, start_date: str, end_date: str) -> str:
    query = urlencode(
        {
            "period1": date_to_epoch(start_date),
            "period2": inclusive_end_to_epoch(end_date),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    return f"{YAHOO_CHART_BASE}/{quote(yahoo_symbol(symbol))}?{query}"


def fetch_text(url: str, *, retries: int = 4, sleep_sec: float = 1.0) -> str:
    curl_path = shutil.which("curl")
    if curl_path:
        command = [
            curl_path,
            "-fsSL",
            "--retry",
            str(max(0, retries - 1)),
            "--retry-delay",
            str(max(1, int(sleep_sec))),
            "--retry-all-errors",
            "-A",
            USER_AGENT,
            "-H",
            "Accept: application/json,text/html,*/*",
            url,
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode == 0:
            return completed.stdout

    request = Request(
        url,
        headers={
            "Accept": "application/json,text/html,*/*",
            "User-Agent": USER_AGENT,
        },
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=45) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
        except URLError as exc:
            last_error = exc
            if attempt == retries - 1:
                raise RuntimeError(f"Network error while fetching {url}: {exc}") from exc
        time.sleep(sleep_sec * (2**attempt))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def fetch_json(url: str, *, retries: int = 4, sleep_sec: float = 1.0) -> dict[str, Any]:
    return json.loads(fetch_text(url, retries=retries, sleep_sec=sleep_sec))


def parse_sp500_tickers(page_html: str) -> list[str]:
    match = re.search(
        r"<table[^>]*id=[\"']constituents[\"'][^>]*>(.*?)</table>",
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    table_html = match.group(1) if match else page_html
    tickers: list[str] = []
    seen: set[str] = set()
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.IGNORECASE | re.DOTALL):
        cell_match = re.search(
            r"<td[^>]*>\s*<a[^>]*>(.*?)</a>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not cell_match:
            continue
        ticker = re.sub(r"<[^>]+>", "", cell_match.group(1))
        ticker = yahoo_symbol(html.unescape(ticker))
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


def fetch_sp500_tickers() -> list[str]:
    tickers = parse_sp500_tickers(fetch_text(SP500_URL))
    if len(tickers) < 450:
        raise RuntimeError(f"Expected S&P 500 ticker list, got only {len(tickers)} symbols")
    return tickers


def rows_from_chart_response(payload: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo chart error for {symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        return []

    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quotes = indicators.get("quote") or []
    if not quotes:
        return []

    quote_data = quotes[0]
    adjclose_data = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
    rows: list[dict[str, Any]] = []
    normalized_symbol = yahoo_symbol(symbol)

    for index, timestamp in enumerate(timestamps):
        open_px = value_at(quote_data.get("open"), index)
        high_px = value_at(quote_data.get("high"), index)
        low_px = value_at(quote_data.get("low"), index)
        close_px = value_at(quote_data.get("close"), index)
        if None in {open_px, high_px, low_px, close_px}:
            continue

        adj_close = value_at(adjclose_data, index)
        volume = value_at(quote_data.get("volume"), index)
        rows.append(
            {
                "date": datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date().isoformat(),
                "timestamp": int(timestamp),
                "symbol": normalized_symbol,
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "close": close_px,
                "adj_close": adj_close if adj_close is not None else close_px,
                "volume": int(volume) if volume is not None else "",
            }
        )
    return rows


def value_at(values: Any, index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def fetch_ohlc(symbol: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    return rows_from_chart_response(fetch_json(build_chart_url(symbol, start_date, end_date)), symbol)


def safe_symbol_name(symbol: str) -> str:
    return yahoo_symbol(symbol).replace("/", "_")


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_ticker_file(path: Path) -> list[str]:
    tickers: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            token = line.strip().split(",")[0].strip()
            if token and not token.startswith("#"):
                tickers.append(yahoo_symbol(token))
    return tickers


def resolve_tickers(args: argparse.Namespace) -> list[str]:
    tickers: list[str] = []
    if args.tickers:
        tickers.extend(yahoo_symbol(symbol) for symbol in args.tickers)
    if args.ticker_file:
        tickers.extend(read_ticker_file(args.ticker_file))
    if not tickers:
        tickers = fetch_sp500_tickers()

    seen: set[str] = set()
    unique_tickers: list[str] = []
    for ticker in tickers:
        if ticker not in seen:
            seen.add(ticker)
            unique_tickers.append(ticker)
    return unique_tickers


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "start_date": "", "end_date": "", "latest_close": ""}
    return {
        "rows": len(rows),
        "start_date": rows[0]["date"],
        "end_date": rows[-1]["date"],
        "latest_close": rows[-1]["close"],
    }


def write_summary(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["symbol", "status", "file", "rows", "start_date", "end_date", "latest_close", "error"]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--output-dir", type=Path, default=Path("data/yahoo_us_ohlc_2016_today"))
    parser.add_argument("--tickers", nargs="*", help="Optional ticker override, e.g. AAPL MSFT BRK.B")
    parser.add_argument("--ticker-file", type=Path, help="Optional text/CSV file with one ticker per row")
    parser.add_argument("--sleep-sec", type=float, default=0.25)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.start > args.end:
        raise ValueError("--start must be on or before --end")
    if args.sleep_sec < 0:
        raise ValueError("--sleep-sec must be non-negative")

    tickers = resolve_tickers(args)
    records: list[dict[str, Any]] = []
    summary_path = args.output_dir / "_summary.csv"
    ticker_path = args.output_dir / "_tickers.csv"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ticker_path.write_text("symbol\n" + "\n".join(tickers) + "\n", encoding="utf-8")

    print(f"tickers: {len(tickers)}")
    print(f"date range: {args.start} -> {args.end}")
    print(f"output: {args.output_dir}")

    for index, ticker in enumerate(tickers, start=1):
        output_path = args.output_dir / f"{safe_symbol_name(ticker)}_1d_ohlcv.csv"
        record: dict[str, Any] = {
            "symbol": ticker,
            "status": "pending",
            "file": str(output_path),
            "rows": 0,
            "start_date": "",
            "end_date": "",
            "latest_close": "",
            "error": "",
        }

        if output_path.exists() and not args.overwrite:
            with output_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            record.update({"status": "skipped_existing", **summarize_rows(rows)})
            records.append(record)
            print(f"[{index}/{len(tickers)}] {ticker}: skipped existing {record['rows']} rows")
            write_summary(records, summary_path)
            continue

        try:
            rows = fetch_ohlc(ticker, args.start, args.end)
            write_csv(rows, output_path)
            record.update({"status": "ok", **summarize_rows(rows)})
            print(
                f"[{index}/{len(tickers)}] {ticker}: wrote {record['rows']} rows "
                f"{record['start_date']} -> {record['end_date']}"
            )
        except Exception as exc:
            record.update({"status": "error", "error": str(exc)})
            print(f"[{index}/{len(tickers)}] {ticker}: ERROR {exc}", file=sys.stderr)

        records.append(record)
        write_summary(records, summary_path)
        if index < len(tickers) and args.sleep_sec:
            time.sleep(args.sleep_sec)

    ok_count = sum(1 for record in records if record["status"] in {"ok", "skipped_existing"})
    error_count = sum(1 for record in records if record["status"] == "error")
    print(f"summary: {summary_path}")
    print(f"completed: {ok_count}, errors: {error_count}")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
