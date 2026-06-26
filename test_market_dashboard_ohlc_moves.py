#!/usr/bin/env python3
"""Tests for OHLC daily percent-move payloads."""

from __future__ import annotations

from datetime import date

from market_dashboard import JS
from market_dashboard import recent_ohlc_rows


def ohlc(day: int, close: float) -> dict[str, object]:
    return {
        "date": date(2026, 6, day),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
    }


def test_recent_ohlc_rows_adds_percent_move_from_previous_close() -> None:
    rows = [ohlc(1, 100), ohlc(2, 110), ohlc(3, 99)]

    recent = recent_ohlc_rows(rows, limit=2)

    assert [row["date"] for row in recent] == ["2026-06-02", "2026-06-03"]
    assert recent[0]["prev_close"] == 100
    assert recent[0]["change_pct"] == 10.0
    assert recent[1]["prev_close"] == 110
    assert recent[1]["change_pct"] == -10.0


def test_move_chart_keeps_rotated_date_labels_inside_svg_viewbox() -> None:
    assert "bottom: 84" in JS
    assert 'const dateLabelY = height - 30;' in JS
    assert 'rotate(-48 ${xx} ${dateLabelY})' in JS
