from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from fetch_japan_bond_ohlc import close_only_row
from stage_chinabond_history import CLOSE_ONLY_SOURCE, TENORS, stage_history


FIELDS = ["date", "timestamp", "open", "high", "low", "close", "volume", "source_symbol", "source"]
BASELINE_ROWS = [
    ["2021-11-22", "", "", "", "", "2.222", "", "CFETS", "official close"],
    ["2021-11-24", "1637712000", "2.2", "2.8", "2.15", "2.6", "7", "WSCN", "official candle"],
]


def make_baseline(baseline_dir: Path) -> None:
    baseline_dir.mkdir()
    for tenor in TENORS:
        with (baseline_dir / f"CN_{tenor}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(FIELDS)
            writer.writerows(BASELINE_ROWS)


def test_staged_chinabond_history_adds_only_missing_dates_and_preserves_prior_rows(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    output_dir = tmp_path / "staged"
    make_baseline(baseline_dir)
    samples = [
        close_only_row("2021-11-19", 2.1234),
        close_only_row("2021-11-22", 2.2200),
        close_only_row("2021-11-23", 2.3456),
        close_only_row("2021-11-24", 2.5700),
        close_only_row("2021-11-25", 2.7777),
    ]
    report = stage_history(
        baseline_dir,
        output_dir,
        {tenor: samples for tenor in TENORS},
        start=date(2021, 11, 19),
        end=date(2021, 11, 25),
    )

    for tenor in TENORS:
        key = f"CN_{tenor}"
        with (output_dir / f"{key}.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert [row["date"] for row in rows] == ["2021-11-19", "2021-11-22", "2021-11-23", "2021-11-24"]
        assert rows[1] == dict(zip(FIELDS, BASELINE_ROWS[0]))
        assert rows[3] == dict(zip(FIELDS, BASELINE_ROWS[1]))
        for row in (rows[0], rows[2]):
            assert [row[field] for field in ("open", "high", "low")] == ["", "", ""]
            assert row["close"]
            assert row["source"] == CLOSE_ONLY_SOURCE
        assert report[key]["preserved_dates"] == 2
        assert report[key]["preserved_complete_ohlc"] == 1
        assert report[key]["new_closes"] == 2


def test_staged_chinabond_history_rejects_unverified_tenor_before_creating_any_outputs(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    output_dir = tmp_path / "staged"
    make_baseline(baseline_dir)
    sample = close_only_row("2021-11-22", 2.222)
    with pytest.raises(ValueError, match="CN_30Y: no source dates match the production series"):
        stage_history(
            baseline_dir,
            output_dir,
            {"3M": [sample], "6M": [sample]},
            start=date(2021, 11, 19),
            end=date(2021, 11, 25),
        )

    assert not output_dir.exists()


def test_staged_chinabond_history_rejects_mismatched_rate_level(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    make_baseline(baseline_dir)
    matching = close_only_row("2021-11-22", 2.222)
    wrong_tenor = close_only_row("2021-11-22", 3.222)

    with pytest.raises(ValueError, match=r"CN_30Y: median same-day difference 100\.00 bp"):
        stage_history(
            baseline_dir,
            tmp_path / "staged",
            {"3M": [matching], "6M": [matching], "30Y": [wrong_tenor]},
            start=date(2021, 11, 19),
            end=date(2021, 11, 25),
        )
