from __future__ import annotations

import csv
from datetime import date
from io import StringIO
from pathlib import Path

import pytest

from backfill_us_treasury_history import (
    CACHE_COLUMNS,
    TREASURY_COLUMNS,
    TREASURY_SOURCE,
    history_start,
    parse_treasury_year,
    read_market_cache,
    stage_backfill,
)


def treasury_csv(observations: dict[date, dict[str, str]]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["Date", *TREASURY_COLUMNS.values()])
    writer.writeheader()
    for observed, fields in observations.items():
        writer.writerow({"Date": observed.strftime("%m/%d/%Y"), **fields})
    return buffer.getvalue()


def test_treasury_csv_uses_real_30y_quote_and_preserves_missing_cells() -> None:
    observed = date(2021, 11, 19)
    text = treasury_csv({observed: {"1 Mo": "N/A", "3 Mo": "0.05", "30 Yr": "1.91"}})
    assert parse_treasury_year(text, 2021) == {observed: {"US_3M": "0.05", "US_30Y": "1.91"}}
    with pytest.raises(ValueError, match="nonfinite"):
        parse_treasury_year(treasury_csv({observed: {"30 Yr": "NaN"}}), 2021)


def test_history_start_retains_pre_cutoff_week_and_handles_leap_day() -> None:
    assert history_start(date(2026, 11, 20)) == date(2021, 11, 13)
    assert history_start(date(2028, 2, 29)) == date(2023, 2, 21)


def test_stage_backfill_preserves_every_existing_field_and_clamps_to_each_tenor(tmp_path: Path) -> None:
    inputs = tmp_path / "current"
    inputs.mkdir()
    staged = tmp_path / "staged"
    fields = ["date", *sorted(CACHE_COLUMNS - {"date"}), "extra"]
    reference = {
        "timestamp": "1767200000", "open": "4.3100", "high": "4.35", "low": "4.25",
        "close": "4.27", "source": "WallStreetCN", "extra": "unchanged provenance",
    }
    end = date(2026, 11, 20)
    nov_19 = date(2026, 11, 19)
    older = date(2021, 11, 12)
    for key in TREASURY_COLUMNS:
        with (inputs / f"{key}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"date": older.isoformat(), **reference})
            writer.writerow({"date": (nov_19 if key == "US_1M" else end).isoformat(), **reference})

    def fetch_year(year: int) -> str:
        values = {column: "3.00" for column in TREASURY_COLUMNS.values()}
        if year == 2026:
            return treasury_csv({date(2026, 11, 18): values, nov_19: values, end: values})
        return treasury_csv({date(year, 11, 12): values, date(year, 11, 15): values})

    report = stage_backfill(inputs, staged, as_of=end, fetch_year=fetch_year)
    assert report["start"] == "2021-11-13"
    assert set(report["staged_files"]) == {f"{key}.csv" for key in TREASURY_COLUMNS}
    for key in TREASURY_COLUMNS:
        baseline_fields, before = read_market_cache(inputs / f"{key}.csv")
        output_fields, after = read_market_cache(staged / f"{key}.csv")
        assert output_fields == baseline_fields
        assert all(after[dt] == record for dt, record in before.items())
        assert max(after) == (nov_19 if key == "US_1M" else end)
        added = after[date(2026, 11, 18)]
        assert added["close"] == "3.00"
        assert added["open"] == added["high"] == added["low"] == ""
        assert added["source"] == TREASURY_SOURCE

    assert stage_backfill(staged, tmp_path / "recheck", as_of=end, fetch_year=fetch_year)["staged_files"] == []
