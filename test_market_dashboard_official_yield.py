"""Official closing-yield history must survive cache refreshes without creating OHLC."""

import csv
from datetime import date

import pytest

from market_dashboard import (
    CLOSE_ONLY_YIELD_SOURCES,
    has_complete_ohlc,
    merge_ohlc_rows,
    read_ohlc,
    recent_ohlc_rows,
    write_ohlc,
)


@pytest.mark.parametrize("source", sorted(CLOSE_ONLY_YIELD_SOURCES))
def test_official_close_survives_cache_round_trip_without_fake_ohlc(tmp_path, source):
    path = tmp_path / "yield.csv"
    original = {"date": "2021-11-22", "close": 2.30, "source": source}
    write_ohlc(path, [original])
    fills = read_ohlc(path)
    assert not has_complete_ohlc(fills[0])

    flat = {"date": "2021-11-22", "open": 2.20, "high": 2.20, "low": 2.20, "close": 2.20}
    merged = merge_ohlc_rows(fills, [flat])
    assert merged == [dict(fills[0], date=original["date"])]
    write_ohlc(path, merged)
    with path.open() as handle:
        row = next(csv.DictReader(handle))
    assert [row[key] for key in ("open", "high", "low")] == ["", "", ""]
    public = recent_ohlc_rows(read_ohlc(path))[0]
    assert public == {
        "date": "2021-11-22", "open": None, "high": None, "low": None,
        "close": 2.30, "close_only": True, "source": source,
    }

    full = dict(flat, open=2.19, high=2.23, low=2.18)
    assert merge_ohlc_rows(fills, [full]) == [full]
    assert merge_ohlc_rows([full], fills) == [full]
    assert fills[0]["date"] == date(2021, 11, 22)


def test_backfill_does_not_shorten_the_existing_chart_history():
    def row(day):
        return {"date": date(2021, 11, day), "open": 2.19, "high": 2.23, "low": 2.18, "close": 2.20}

    fill = dict(row(23), source="U.S. Treasury official par yield (close-only)")
    history = recent_ohlc_rows([row(22), fill, row(24)], limit=2)
    assert [point["date"] for point in history] == ["2021-11-22", "2021-11-23", "2021-11-24"]
