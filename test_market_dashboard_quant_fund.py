#!/usr/bin/env python3
"""Tests for the quiet quant-fund section."""

from __future__ import annotations

from market_dashboard import render_html


def test_quant_fund_is_hidden_behind_plain_notes_link_with_smooth_percent_curves() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": [],
            "series_status": [],
            "notes": ["政策新闻雷达只做加息、降息、维持利率相关文本筛选。"],
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

    assert '<a class="quiet-quant-link" href="#quant-fund">量化基金</a>' in html
    assert '<section class="panel quant-fund-detail" id="quant-fund">' in html
    assert '<div class="quant-fund-head">' in html
    assert html.index('<section class="notes">') < html.index('<a class="quiet-quant-link" href="#quant-fund">量化基金</a>')
    assert html.index('<a class="quiet-quant-link" href="#quant-fund">量化基金</a>') < html.index('<section class="panel quant-fund-detail" id="quant-fund">')
    assert '<section class="panel quant-fund-bottom" id="quant-fund">' not in html
    assert '<a class="quant-fund-dock" href="#quant-fund">' not in html
    assert '<section class="quant-fund-page" id="quant-fund">' not in html
    assert '<a class="quant-back" href="#">← 返回</a>' not in html
    assert '<details class="quant-fund-widget">' not in html
    assert ".quiet-quant-link {" in html
    assert ".quant-fund-detail { display: none;" in html
    assert ".quant-fund-detail:target { display: block;" in html
    assert ".quant-fund-bottom {" not in html
    assert ".quant-fund-dock {" not in html
    assert ".quant-fund-page { display: none;" not in html
    assert ".quant-fund-page:target" not in html
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
