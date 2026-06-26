#!/usr/bin/env python3
"""Tests for the quiet quant-fund widget."""

from __future__ import annotations

from market_dashboard import render_html


def test_quant_fund_entry_is_bottom_dock_and_opens_dedicated_view_with_smooth_percent_curves() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
            "quant_fund": {
                "generated_at": "2026-06-26T00:00:00",
                "futures": {
                    "label": "期货",
                    "status": "ok",
                    "base_configured": True,
                    "points": [
                        {"date": "2026-04-01", "pct": 0.0},
                        {"date": "2026-04-02", "pct": 2.0},
                        {"date": "2026-04-03", "pct": 1.0},
                    ],
                },
                "options": {
                    "label": "期权",
                    "status": "ok",
                    "base_configured": True,
                    "points": [
                        {"date": "2026-04-01", "pct": 0.0},
                        {"date": "2026-04-02", "pct": -1.0},
                        {"date": "2026-04-03", "pct": 3.0},
                    ],
                },
                "equity": {"label": "股指", "status": "pending", "points": []},
            },
        }
    )

    assert '<a class="quant-fund-dock" href="#quant-fund">' in html
    assert '<section class="quant-fund-page" id="quant-fund">' in html
    assert '<a class="quant-back" href="#">← 返回</a>' in html
    assert '<details class="quant-fund-widget">' not in html
    assert ".quant-fund-dock {" in html
    assert "position: fixed;" in html
    assert ".quant-fund-page { display: none;" in html
    assert ".quant-fund-page:target" in html
    assert "期货" in html
    assert "期权" in html
    assert "股指" in html
    assert "待定" in html
    assert "本金已配置" in html
    assert "base_usd" not in html
    assert 'class="quant-curve-line"' in html
    assert " C " in html
    assert "<polyline" not in html
    assert "BINANCE" not in html
    assert "API_KEY" not in html
    assert "SECRET" not in html
    assert "BTCUSDT" not in html
    assert "USDT" not in html
    assert "USDC" not in html
    assert "BTC-260" not in html
