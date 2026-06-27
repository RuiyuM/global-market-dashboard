#!/usr/bin/env python3
"""Layout defaults for the main dashboard."""

from __future__ import annotations

from market_dashboard import render_html


def minimal_snapshot() -> dict[str, object]:
    return {
        "countries": [],
        "daily_move_alert": {"items": [], "top_candidate": None, "window": "30D", "threshold_top_pct": 20.0},
        "volatility_rankings": {"bond": [], "equity": [], "fx": []},
        "fx_rank_details": {},
        "second_order_monitor": [],
        "fx_flows": [],
        "series_status": [],
        "notes": [],
        "generated_at": "2026-06-26T00:00:00",
    }


def test_flow_panel_precedes_collapsed_country_panel_and_defaults_expanded() -> None:
    html = render_html(minimal_snapshot())

    assert html.index("<h2>三币种资金流向</h2>") < html.index("<summary><span>国家面板</span>")
    assert '<button type="button" class="flow-panel-toggle" data-flow-panel-toggle aria-expanded="true">' in html
    assert '<span class="toggle-icon">▾</span><span>收起</span>' in html
    assert '<div class="flow-grid" data-flow-panel-body>' in html
    assert '<div class="flow-grid" data-flow-panel-body hidden>' not in html
    assert '<details class="panel country-panel">' in html
    assert '<details class="panel country-panel" open>' not in html
    assert "<summary><span>国家面板</span>" in html
