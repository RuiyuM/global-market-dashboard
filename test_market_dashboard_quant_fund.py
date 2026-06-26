#!/usr/bin/env python3
"""Tests for the quiet quant-fund widget."""

from __future__ import annotations

from market_dashboard import render_html


def test_quant_fund_widget_defaults_collapsed_and_uses_smooth_percent_curves() -> None:
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
                    "label": "BTCUSDT 期货",
                    "status": "ok",
                    "base_configured": True,
                    "points": [
                        {"date": "2026-04-01", "pct": 0.0},
                        {"date": "2026-04-02", "pct": 2.0},
                        {"date": "2026-04-03", "pct": 1.0},
                    ],
                },
                "options": {
                    "label": "期权 USDT+USDC",
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

    opening = '<details class="quant-fund-widget">'
    assert opening in html
    assert "open" not in opening
    assert "<summary><span>量化基金</span>" in html
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
