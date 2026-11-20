#!/usr/bin/env python3
"""Stage official ChinaBond closes only for missing public-history dates."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from fetch_global_bond_ohlc import fetch_chinabond_pbc_history_rows_by_tenor
from market_dashboard import has_complete_ohlc


TENORS = ("3M", "6M", "30Y")
CLOSE_ONLY_SOURCE = "ChinaBond PBC official yield (close-only)"
REQUIRED_FIELDS = {"date", "timestamp", "open", "high", "low", "close", "source_symbol", "source"}
MAX_MEDIAN_ABSOLUTE_OVERLAP_BP = 5.0


def stage_history(
    baseline_dir: Path,
    output_dir: Path,
    observations: dict[str, list[dict[str, Any]]],
    *,
    start: date,
    end: date,
) -> dict[str, dict[str, Any]]:
    if start > end:
        raise ValueError("start must be on or before end")
    if baseline_dir.resolve() == output_dir.resolve():
        raise ValueError("staging output must differ from the baseline directory")

    prepared: list[tuple[Path, list[str], list[dict[str, Any]]]] = []
    report: dict[str, dict[str, Any]] = {}
    for tenor in TENORS:
        key = f"CN_{tenor}"
        filename = f"{key}.csv"
        destination = output_dir / filename
        if destination.exists():
            raise FileExistsError(destination)
        with (baseline_dir / filename).open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            baseline_rows = list(reader)
        if not REQUIRED_FIELDS.issubset(fieldnames) or not baseline_rows:
            raise ValueError(f"{key}: expected populated production CSV")
        baseline = {date.fromisoformat(row["date"]): row for row in baseline_rows}
        if len(baseline) != len(baseline_rows):
            raise ValueError(f"{key}: duplicate dates in the production baseline")

        historical_end = min(end, max(baseline))
        merged = dict(baseline)
        overlap_differences = []
        added_dates = []
        for row in observations.get(tenor, []):
            day = date.fromisoformat(row["date"])
            if not start <= day <= end:
                raise ValueError(f"{key}: source returned {day} outside requested range")
            close = float(row["close"])
            if not math.isfinite(close):
                raise ValueError(f"{key}: non-finite yield on {day}")
            if day in baseline:
                overlap_differences.append(abs(float(baseline[day]["close"]) - close) * 100)
            elif day <= historical_end:
                merged[day] = {
                    "date": day.isoformat(),
                    "timestamp": row["timestamp"],
                    "open": "",
                    "high": "",
                    "low": "",
                    "close": close,
                    "source_symbol": f"ChinaBond CCDC:{tenor}",
                    "source": CLOSE_ONLY_SOURCE,
                }
                added_dates.append(day)

        if not overlap_differences:
            raise ValueError(f"{key}: no source dates match the production series")
        median_overlap_bp = median(overlap_differences)
        if median_overlap_bp > MAX_MEDIAN_ABSOLUTE_OVERLAP_BP:
            raise ValueError(f"{key}: median same-day difference {median_overlap_bp:.2f} bp exceeds 5 bp")
        report[key] = {
            "baseline_first": min(baseline).isoformat(),
            "first": min(merged).isoformat(),
            "last": max(merged).isoformat(),
            "preserved_dates": len(baseline),
            "preserved_complete_ohlc": sum(has_complete_ohlc(row) for row in baseline.values()),
            "new_closes": len(added_dates),
            "first_added": min(added_dates).isoformat() if added_dates else None,
            "last_added": max(added_dates).isoformat() if added_dates else None,
            "overlap_dates": len(overlap_differences),
            "median_abs_overlap_bp": round(median_overlap_bp, 3),
            "max_abs_overlap_bp": round(max(overlap_differences), 3),
        }
        if added_dates:
            prepared.append((destination, fieldnames, [merged[day] for day in sorted(merged)]))

    output_dir.mkdir(parents=True, exist_ok=True)
    for destination, fieldnames, rows in prepared:
        with destination.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    history = fetch_chinabond_pbc_history_rows_by_tenor(args.start_date, args.end_date, TENORS, sleep_sec=0.1)
    report = stage_history(args.baseline_dir, args.output_dir, history, start=args.start_date, end=args.end_date)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
