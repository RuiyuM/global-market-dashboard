#!/usr/bin/env python3
"""Tests for the quiet quant-fund section."""

from __future__ import annotations

import re

from market_dashboard import (
    public_market_snapshot,
    render_html,
    render_quant_curve,
    render_quant_fund_page,
)


def quant_snapshot() -> dict:
    return {
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
    }


def test_public_market_snapshot_does_not_embed_protected_quant_data() -> None:
    snapshot = {"generated_at": "2026-06-27T00:00:00Z", "quant_fund": quant_snapshot()}
    public = public_market_snapshot(snapshot)

    assert public == {"generated_at": "2026-06-27T00:00:00Z"}
    assert "quant_fund" in snapshot


def test_quant_fund_link_is_plain_notes_link_to_separate_page() -> None:
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
            "quant_fund": quant_snapshot(),
        }
    )

    assert '<a class="quiet-quant-link" href="quant_fund.html">量化基金</a>' in html
    assert html.index('<section class="notes">') < html.index('<a class="quiet-quant-link" href="quant_fund.html">量化基金</a>')
    assert '<section class="panel quant-fund-detail" id="quant-fund">' not in html
    assert '<section class="panel quant-fund-bottom" id="quant-fund">' not in html
    assert '<a class="quant-fund-dock" href="#quant-fund">' not in html
    assert '<section class="quant-fund-page" id="quant-fund">' not in html
    assert '<a class="quant-back" href="#">← 返回</a>' not in html
    assert '<details class="quant-fund-widget">' not in html
    assert ".quiet-quant-link {" in html
    assert ".quant-fund-bottom {" not in html
    assert ".quant-fund-dock {" not in html
    assert ".quant-fund-page { display: none;" not in html
    assert ".quant-fund-page:target" not in html
    assert "期货" not in html
    assert "期权" not in html
    assert "股指" in html
    assert "本金已配置" not in html
    assert "base_usd" not in html
    assert "等待本金" not in html
    assert "历史种子" not in html


def test_quant_fund_separate_page_contains_curves_and_back_link() -> None:
    html = render_quant_fund_page(quant_snapshot())

    assert '<a class="quant-back" href="index.html">返回</a>' in html
    assert '<section class="panel quant-fund-detail">' in html
    assert '<a class="quant-card" href="#quant-detail-futures">' in html
    assert '<a class="quant-card" href="#quant-detail-options">' in html
    assert '<a class="quant-card" href="#quant-detail-equity">' in html
    assert '<section class="panel quant-detail-panel" id="quant-detail-futures">' in html
    assert '<section class="panel quant-detail-panel" id="quant-detail-options">' in html
    assert '<section class="panel quant-detail-panel quant-detail-empty" id="quant-detail-equity">' in html
    assert ".quant-detail-panel { display: none;" in html
    assert ".quant-detail-panel:target { display: block;" in html
    assert "期货" in html
    assert "期权" in html
    assert "股指" in html
    assert "待定" in html
    assert "coming soon in 2026 3季度末" in html
    assert "本金已配置" not in html
    assert "本金未配置" not in html
    assert "等待本金" not in html
    assert "历史种子" not in html
    assert "百分比曲线" not in html
    assert 'class="quant-curve-line"' in html
    assert 'class="quant-curve quant-curve-large"' in html
    assert '<div class="quant-detail-title"><h3>期货</h3><span class="quant-chart-kicker"><b>Curve</b><em>daily percentage points</em></span></div>' in html
    assert 'class="quant-chart-title"' not in html
    assert 'class="quant-chart-subtitle"' not in html
    assert '<text class="quant-axis-date" ' in html
    assert '>04-01</text>' in html
    assert '>04-02</text>' in html
    assert '>04-03 +1.00%</text>' in html
    assert 'class="quant-peak-line"' in html
    assert 'class="quant-start-line"' in html
    assert "Max DD" in html
    assert " C " in html
    assert "<polyline" not in html
    assert "quant-drawdown-line" not in html
    assert "quant-drawdown-area" not in html
    assert "Curve and Drawdown" not in html
    assert "Entry Price" not in html
    assert "USD" not in html
    assert "base_configured" not in html
    assert "trade_count" not in html
    assert "BINANCE" not in html
    assert "API_KEY" not in html
    assert "SECRET" not in html
    assert "USDT" not in html
    assert "USDC" not in html


def test_quant_fund_large_curve_leaves_room_for_rotated_date_labels() -> None:
    points = [
        {"date": f"2026-04-{day:02d}", "pct": (day % 7) - 3}
        for day in range(1, 29)
    ]
    html = render_quant_curve(points, large=True)

    viewbox = re.search(r'viewBox="0 0 920 ([0-9.]+)"', html)
    assert viewbox
    height = float(viewbox.group(1))
    y_values = [float(value) for value in re.findall(r'class="quant-axis-date" x="[^"]+" y="([0-9.]+)"', html)]
    assert y_values
    assert height - max(y_values) >= 76
