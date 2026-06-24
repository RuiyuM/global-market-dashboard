#!/usr/bin/env python3
"""Fetch OHLC bars from the WallstreetCN chart data endpoint."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://api-ddc-wscn.awtmt.com"
FIELDS = ["tick_at", "open_px", "close_px", "high_px", "low_px"]
PERIOD_SECONDS = {
    "1": 60,
    "5": 300,
    "15": 900,
    "30": 1800,
    "60": 3600,
    "240": 14400,
    "1D": 86400,
    "D": 86400,
    "1W": 604800,
    "W": 604800,
    "1M": 2592000,
    "M": 2592000,
}


def period_seconds(interval: str) -> int:
    normalized = interval.upper()
    if normalized in PERIOD_SECONDS:
        return PERIOD_SECONDS[normalized]
    raise ValueError(f"Unsupported interval: {interval}")


def build_kline_url(
    symbol: str,
    interval: str,
    tick_count: int,
    timestamp: int,
    *,
    base_url: str = BASE_URL,
) -> str:
    query = urlencode(
        {
            "prod_code": symbol.upper(),
            "tick_count": tick_count,
            "period_type": period_seconds(interval),
            "fields": ",".join(FIELDS),
            "timestamp": timestamp,
            "adjust_price_type": "forward",
        }
    )
    return f"{base_url}/market/kline?{query}"


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36"
            ),
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error while fetching {url}: {exc}") from exc


def rows_from_response(payload: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    if payload.get("message") != "OK":
        raise RuntimeError(f"WSCN API returned {payload.get('message')}: {payload}")

    data = payload.get("data") or {}
    fields = data.get("fields") or []
    candle = data.get("candle") or {}
    series = candle.get(symbol.upper()) or candle.get(symbol) or {}
    lines = series.get("lines") or []

    rows = []
    for line in lines:
        values = dict(zip(fields, line))
        timestamp = int(values["tick_at"])
        rows.append(
            {
                "date": datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat(),
                "timestamp": timestamp,
                "open": float(values["open_px"]),
                "high": float(values["high_px"]),
                "low": float(values["low_px"]),
                "close": float(values["close_px"]),
            }
        )
    return rows


def next_page_timestamp(rows: list[dict[str, Any]]) -> int:
    return min(row["timestamp"] for row in rows)


def fetch_ohlc(symbol: str, interval: str, total: int, page_size: int) -> list[dict[str, Any]]:
    rows_by_timestamp: dict[int, dict[str, Any]] = {}
    timestamp = 2_147_483_647

    while len(rows_by_timestamp) < total:
        count = min(page_size, total - len(rows_by_timestamp))
        url = build_kline_url(symbol, interval, count, timestamp)
        page_rows = rows_from_response(fetch_json(url), symbol)
        if not page_rows:
            break

        for row in page_rows:
            rows_by_timestamp[row["timestamp"]] = row

        oldest = next_page_timestamp(page_rows)
        next_timestamp = oldest
        if next_timestamp >= timestamp:
            break
        timestamp = next_timestamp
        time.sleep(0.15)

    return sorted(rows_by_timestamp.values(), key=lambda row: row["timestamp"])[-total:]


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "timestamp", "open", "high", "low", "close"],
        )
        writer.writeheader()
        writer.writerows(rows)


def default_output_path(symbol: str, interval: str) -> Path:
    safe_symbol = symbol.upper().replace(".", "_").replace("/", "_")
    safe_interval = interval.upper().replace("/", "_")
    return Path("data") / f"{safe_symbol}_{safe_interval}_ohlc.csv"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download OHLC bars from the WallstreetCN chart endpoint."
    )
    parser.add_argument("symbols", nargs="*", default=["JPYCNY.OTC"])
    parser.add_argument("--interval", default="1D")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.count <= 0:
        raise ValueError("--count must be positive")
    if args.page_size <= 0:
        raise ValueError("--page-size must be positive")

    for symbol in args.symbols:
        rows = fetch_ohlc(symbol, args.interval, args.count, args.page_size)
        output_path = args.output_dir / default_output_path(symbol, args.interval).name
        write_csv(rows, output_path)
        print(f"{symbol.upper()}: wrote {len(rows)} rows to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
