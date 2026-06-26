#!/usr/bin/env python3
"""Tests for OHLC daily percent-move payloads."""

from __future__ import annotations

from datetime import date

from market_dashboard import JS
from market_dashboard import recent_ohlc_rows
from market_dashboard import render_html


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


def test_ohlc_panel_exposes_comparison_selector() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [
                {
                    "key": "US_10Y",
                    "country": "美国",
                    "group": "债券",
                    "label": "美国10年国债",
                    "unit": "pct",
                    "metrics": {},
                    "summary": {},
                    "ohlc": [],
                }
            ],
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )

    assert '<label class="ohlc-compare"' in html
    assert 'id="ohlc-compare-select"' in html
    assert '<option value="">无比较</option>' in html


def test_ohlc_javascript_supports_comparison_normalization() -> None:
    assert 'const compareSelect = document.getElementById("ohlc-compare-select");' in JS
    assert "const comparisonFor = (primaryItem) =>" in JS
    assert "const normalizeOhlcSeries = (bars) =>" in JS
    assert "range_min" in JS
    assert "(number - rangeMin) / spread * 100" in JS
    assert "区间归一化 0-100" in JS


def test_move_chart_only_mentions_blue_compare_line_when_comparison_exists() -> None:
    assert "const moveCompareNote = compareItem ?" in JS
    assert "柱=主标的单日涨跌幅，蓝线=比较标的" not in JS


def test_ohlc_zoom_buttons_use_requested_direction() -> None:
    assert 'zoomInButton?.addEventListener("click", () => zoomChart(1));' in JS
    assert 'zoomOutButton?.addEventListener("click", () => zoomChart(-1));' in JS


def test_ohlc_comparison_legend_uses_inline_tspans_to_avoid_overlap() -> None:
    assert "const legendY = 18;" in JS
    assert "<tspan" in JS
    assert 'dx="16"' in JS
    assert '比较：${esc(compareItem.label)}' in JS
    assert "legendCompareY" not in JS
    assert 'x="${margin.left + 184}" y="16"' not in JS


def test_data_status_panel_defaults_collapsed() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": [],
            "series_status": [
                {
                    "key": "US_10Y",
                    "label": "美国10年国债",
                    "source": "WSCN",
                    "symbol": "US10YR.OTC",
                    "latest_date": "2026-06-26",
                    "latest": 4.25,
                    "stale": False,
                }
            ],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )

    opening = '<details class="panel status-panel">'
    assert opening in html
    assert "open" not in opening
    assert "<summary><span>数据状态</span>" in html
    assert '<table class="status-table">' in html
