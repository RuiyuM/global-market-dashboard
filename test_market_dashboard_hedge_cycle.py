#!/usr/bin/env python3
"""Tests for the bond hedge-cycle reference section."""

from __future__ import annotations

from market_dashboard import render_html


def minimal_hike_example() -> dict:
    return {
        "source": "US2YR.OTC / US10YR.OTC 本地日线",
        "first_hike": "2022-03-16",
        "chart_start": "2022-03-01",
        "chart_end": "2022-03-18",
        "points": [
            {"date": "2022-03-01", "us2y_index": 100.0, "us10y_index": 100.0},
            {"date": "2022-03-18", "us2y_index": 120.0, "us10y_index": 110.0},
        ],
        "phases": [],
    }


def test_hike_cycle_example_is_collapsed_behind_actual_case_button() -> None:
    html = render_html(
        {
            "countries": [],
            "daily_move_alert": {"items": []},
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-27T00:00:00",
            "hike_cycle_example": minimal_hike_example(),
        }
    )

    assert '<div class="hedge-cycle-title">' in html
    assert '<button type="button" class="hike-example-toggle" data-hike-example-toggle aria-expanded="false">实际案例</button>' in html
    assert '<div class="hike-example-wrap" data-hike-example-wrap hidden>' in html
    assert html.index("加息周期") < html.index("实际案例") < html.index("2022 加息周期长短债例子")
    assert 'document.querySelectorAll("[data-hike-example-toggle]")' in html
