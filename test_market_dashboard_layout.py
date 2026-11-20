#!/usr/bin/env python3
"""Layout defaults for the main dashboard."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from market_dashboard import JS, render_html


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
    assert '<div class="flow-panel-body" data-flow-panel-body>' in html
    assert '<div class="flow-panel-body" data-flow-panel-body hidden>' not in html
    assert 'data-flow-view-tab="closed"' in html
    assert 'data-flow-view-panel="closed"' in html
    assert '<details class="panel country-panel">' in html
    assert '<details class="panel country-panel" open>' not in html
    assert "<summary><span>国家面板</span>" in html


def test_all_bond_panel_exposes_day_and_year_windows() -> None:
    html = render_html(minimal_snapshot())
    assert 'id="all-bond-coverage" role="status"' in html
    for days in (30, 90, 180, 360):
        assert f'data-all-bond-window="{days}"' in html
    for years in (2, 3, 4, 5):
        assert f'data-all-bond-window="{years}Y"' in html
    assert 'data-all-bond-window="90" aria-pressed="true"' in html


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for JavaScript behavior checks")
def test_all_bond_years_display_real_coverage_and_break_missing_lines() -> None:
    # Exercise the actual widget callbacks against a small, deliberately gapped country.
    setup = """
const assert = require("node:assert/strict");
const element = (dataset = {}) => ({
  dataset, attributes: {}, style: {}, classList: { toggle() {} },
  querySelectorAll() { return []; },
  addEventListener(event, callback) { this[event] = callback; },
  setAttribute(key, value) { this.attributes[key] = value; },
});
const rows = (values) => ({ ohlc: values.map(([date, close]) => ({ date, close })) });
const ids = {
  "ohlc-chart": element(),
  "all-bond-country-select": element(),
  "all-bond-coverage": element(),
  "all-bond-summary": element(),
  "all-bond-chart": element(),
  "all-bond-legend": element(),
  "spread-data": { textContent: JSON.stringify([{ code: "US", name: "美国", bonds: [
    { key: "fixture1", tenor: "1Y", tenorMonths: 12 },
    { key: "fixture5", tenor: "5Y", tenorMonths: 60 },
    { key: "fixture10", tenor: "10Y", tenorMonths: 120 },
  ] }]) },
  "ohlc-data": { textContent: JSON.stringify({
    fixture1: rows([["2020-02-29", 2], ["2022-02-27", 2], ["2022-02-28", 2], ["2024-02-26", 2], ["2024-02-27", 2], ["2024-02-29", 2.3]]),
    fixture5: rows([["2024-02-26", 3], ["2024-02-27", 3.2], ["2024-02-29", 3.4]]),
    fixture10: rows([["2024-02-26", 4], ["2024-02-27", null], ["2024-02-29", 4.5]]),
  }) },
};
const periods = ["2Y", "5Y"].map((allBondWindow) => element({ allBondWindow }));
const modes = ["grouped", "tenors"].map((allBondMode) => element({ allBondMode }));
globalThis.document = {
  getElementById(id) { return ids[id] || null; },
  querySelector() { return null; },
  querySelectorAll(selector) {
    if (selector === ".all-bond-window") return periods;
    if (selector === ".all-bond-mode") return modes;
    return [];
  },
};
globalThis.window = { addEventListener() {} };
"""
    checks = r"""
periods[0].click();
assert.match(ids["all-bond-coverage"].textContent, /所选 2Y｜2022-02-28 至 2024-02-29/);
assert.match(ids["all-bond-coverage"].textContent, /实际覆盖 2022-02-28 至 2024-02-29/);
assert.match(ids["all-bond-summary"].innerHTML, /2Y变化/);
assert.match(ids["all-bond-summary"].innerHTML, /2024-02-26 至 2024-02-29/);
assert.equal(periods[0].attributes["aria-pressed"], "true");
assert.equal(periods[1].attributes["aria-pressed"], "false");
const chart = ids["all-bond-chart"];
assert.match(chart.innerHTML, /d="M [\d.]+ [\d.]+ M [\d.]+ [\d.]+" fill="none" stroke="#2457a6"/);
assert.match(chart.innerHTML, />2022-02<\/text>/);

periods[1].click();
modes[1].click();
assert.match(ids["all-bond-coverage"].textContent, /所选 5Y｜2019-02-28 至 2024-02-29/);
assert.match(ids["all-bond-coverage"].textContent, /实际覆盖 2020-02-29 至 2024-02-29/);
assert.match(ids["all-bond-summary"].textContent, /2024-02-29 期限范围差 10Y-1Y \+220.0bp/);
assert.match(ids["all-bond-legend"].innerHTML, /2024-02-26 至 2024-02-29 · 2 个数据日/);
"""
    result = subprocess.run(["node", "-"], input=setup + JS + checks, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
