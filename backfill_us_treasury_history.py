#!/usr/bin/env python3
"""Stage public U.S. Treasury close-only rows for dates missing from WSCN caches."""

from __future__ import annotations

import argparse
import calendar
import csv
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TREASURY_SOURCE = "U.S. Treasury official par yield (close-only)"
TREASURY_CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
)
TREASURY_COLUMNS = {
    "US_1M": "1 Mo",
    "US_3M": "3 Mo",
    "US_6M": "6 Mo",
    "US_1Y": "1 Yr",
    "US_2Y": "2 Yr",
    "US_3Y": "3 Yr",
    "US_5Y": "5 Yr",
    "US_7Y": "7 Yr",
    "US_10Y": "10 Yr",
    "US_30Y": "30 Yr",
}
CACHE_COLUMNS = {"date", "timestamp", "open", "high", "low", "close", "volume", "source_symbol", "source"}
BACKFILL_BUFFER_DAYS = 7


def history_start(end: date) -> date:
    year = end.year - 5
    day = min(end.day, calendar.monthrange(year, end.month)[1])
    return end.replace(year=year, day=day) - timedelta(days=BACKFILL_BUFFER_DAYS)


def download_treasury_year(year: int) -> str:
    params = urlencode({
        "_format": "csv",
        "field_tdr_date_value": year,
        "page": "",
        "type": "daily_treasury_yield_curve",
    })
    request = Request(
        f"{TREASURY_CSV_URL.format(year=year)}?{params}",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"},
    )
    with urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8-sig")


def parse_treasury_year(text: str, year: int) -> dict[date, dict[str, str]]:
    reader = csv.DictReader(StringIO(text))
    if not {"Date", *TREASURY_COLUMNS.values()}.issubset(reader.fieldnames or []):
        raise ValueError(f"Treasury {year} CSV is missing required columns")
    rows: dict[date, dict[str, str]] = {}
    for row in reader:
        observed = datetime.strptime(row["Date"], "%m/%d/%Y").date()
        if observed.year != year or observed in rows:
            raise ValueError(f"Treasury {year} CSV contains an unexpected or duplicate date: {observed}")
        values: dict[str, str] = {}
        for key, column in TREASURY_COLUMNS.items():
            value = (row.get(column) or "").strip()
            if not value or value.upper() in {"N/A", "NA"}:
                continue
            try:
                number = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError(f"Treasury {column} {observed} has an invalid yield") from exc
            if not number.is_finite():
                raise ValueError(f"Treasury {column} {observed} has a nonfinite yield")
            values[key] = value
        rows[observed] = values
    if not any(rows.values()):
        raise ValueError(f"Treasury {year} CSV contains no usable yields")
    return rows


def fetch_backfill_history(
    start: date, end: date, *, fetch_year: Callable[[int], str] = download_treasury_year,
) -> dict[date, dict[str, str]]:
    rows: dict[date, dict[str, str]] = {}
    for year in range(start.year, end.year + 1):
        rows.update({
            observed: values
            for observed, values in parse_treasury_year(fetch_year(year), year).items()
            if start <= observed <= end
        })
    if not rows:
        raise ValueError(f"No Treasury observations within {start} to {end}")
    return rows


def read_market_cache(path: Path) -> tuple[list[str], dict[date, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if not CACHE_COLUMNS.issubset(fields) or len(fields) != len(set(fields)):
            raise ValueError(f"Unexpected cache columns: {path}")
        rows = {}
        for row in reader:
            if None in row or None in row.values():
                raise ValueError(f"Malformed market cache row: {path}")
            observed = date.fromisoformat(row["date"])
            if observed in rows:
                raise ValueError(f"Duplicate cache date {observed}: {path}")
            rows[observed] = row
    if not rows:
        raise ValueError(f"Missing WSCN history in {path}")
    return fields, rows


def wscn_latest(existing: dict[date, dict[str, str]], key: str) -> date:
    # These caches are WSCN-owned. Historical WSCN rows can lack source metadata.
    observed = [dt for dt, row in existing.items() if row["source"] != TREASURY_SOURCE]
    if not observed:
        raise ValueError(f"No existing WSCN observation for {key}")
    return max(observed)


def merge_missing_dates(
    existing: dict[date, dict[str, str]],
    history: dict[date, dict[str, str]],
    key: str,
    fields: list[str],
    end: date,
) -> tuple[dict[date, dict[str, str]], dict[str, str | int | None]]:
    missing = [dt for dt in sorted(history) if dt <= end and dt not in existing]
    added = {}
    for dt in missing:
        close = history[dt].get(key)
        if close is None:
            continue
        row = dict.fromkeys(fields, "")
        row.update({
            "date": dt.isoformat(),
            "timestamp": str(int(datetime.combine(dt, time.min, tzinfo=timezone.utc).timestamp())),
            "close": close,
            "source_symbol": TREASURY_COLUMNS[key],
            "source": TREASURY_SOURCE,
        })
        added[dt] = row
    merged = {**existing, **added}
    return merged, {
        "existing_rows": len(existing),
        "first_before": min(existing).isoformat(),
        "first_after": min(merged).isoformat(),
        "latest_before": max(existing).isoformat(),
        "latest_after": max(merged).isoformat(),
        "added_close_only": len(added),
        "first_added": min(added).isoformat() if added else None,
        "last_added": max(added).isoformat() if added else None,
        "still_missing_in_treasury_dates": len(missing) - len(added),
        "last_eligible_date": end.isoformat(),
    }


def stage_backfill(
    cache_dir: Path,
    output_dir: Path,
    *,
    as_of: date | None = None,
    fetch_year: Callable[[int], str] = download_treasury_year,
) -> dict[str, object]:
    if cache_dir.resolve() == output_dir.resolve():
        raise ValueError("Use a separate staging output directory")
    inputs = {key: read_market_cache(cache_dir / f"{key}.csv") for key in TREASURY_COLUMNS}
    wscn_ends = {key: wscn_latest(rows, key) for key, (_, rows) in inputs.items()}
    end = max(wscn_ends.values())
    if as_of is not None:
        end = min(end, as_of)
    start = history_start(end)
    history = fetch_backfill_history(start, end, fetch_year=fetch_year)
    plans = {}
    reports = {}
    for key, (fields, before) in inputs.items():
        merged, report = merge_missing_dates(before, history, key, fields, min(end, wscn_ends[key]))
        reports[key] = report
        if report["added_close_only"]:
            path = output_dir / f"{key}.csv"
            if path.exists():
                raise FileExistsError(path)
            plans[key] = (path, fields, merged)
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, (path, fields, rows) in plans.items():
        with path.open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows[dt] for dt in sorted(rows))
        output_fields, output_rows = read_market_cache(path)
        before = inputs[key][1]
        if output_fields != fields or any(output_rows.get(dt) != row for dt, row in before.items()):
            raise ValueError(f"Existing dates or source rows changed: {path}")
        if output_rows != rows:
            raise ValueError(f"Staged rows differ from the verified merge: {path}")
    return {
        "source": TREASURY_SOURCE,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "staged_files": [path.name for path, _, _ in plans.values()],
        "series": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, help="Optional ISO date no later than the observed WSCN data")
    args = parser.parse_args()
    print(json.dumps(stage_backfill(args.cache_dir, args.output_dir, as_of=args.as_of), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
