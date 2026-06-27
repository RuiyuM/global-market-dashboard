#!/usr/bin/env python3
"""Validate that the generated market dashboard satisfies the requested coverage."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


SNAPSHOT = Path(__file__).resolve().parent / "dashboard" / "latest_market_snapshot.json"
HTML = Path(__file__).resolve().parent / "dashboard" / "index.html"
QUANT_HTML = Path(__file__).resolve().parent / "dashboard" / "quant_fund.html"
DEFAULT_FX_FLOW_CODE = Path(__file__).resolve().parent / "fx_flow_logic.py"
USER_FX_FLOW_CODE = str(Path(os.environ.get("FX_FLOW_CODE_PATH", str(DEFAULT_FX_FLOW_CODE))))
COUNTRIES = {"美国", "中国", "日本", "德国", "俄罗斯", "韩国"}
POLICY_REGIONS = {"US": "美国", "EU": "欧元区", "JP": "日本", "CN": "中国", "KR": "韩国", "RU": "俄罗斯"}
FIELDS = ["bond_2y", "bond_10y", "equity", "fx"]
CHANGES = ["chg_1d", "chg_7d", "chg_14d", "chg_30d"]
FLOWS = {"中日美", "中德美", "中俄美"}
PERIODS = {"当日", "上日", "当周", "上周", "当月", "上月"}
FLOW_PERIOD_COUNT = len(FLOWS) * len(PERIODS)
VOLS = {"equity", "bond", "fx"}
VOL_WINDOWS = {"7D", "30D"}
VOL_RANKING_ROWS = 6
INLINE_VOL_COUNT = len(COUNTRIES) * len(FIELDS)
ONE_YEAR_BOND_KEYS = {"US_1Y": "美国", "CN_1Y": "中国", "JP_1Y": "日本"}
EXTENDED_BOND_KEYS = {
    "US_1M": "美国",
    "US_3M": "美国",
    "US_6M": "美国",
    "US_3Y": "美国",
    "US_5Y": "美国",
    "US_7Y": "美国",
    "US_30Y": "美国",
    "CN_3Y": "中国",
    "CN_5Y": "中国",
    "CN_7Y": "中国",
}
DERIVATIVE_VOL_COUNT = INLINE_VOL_COUNT + len(ONE_YEAR_BOND_KEYS) + len(EXTENDED_BOND_KEYS)
SECOND_ORDER_WINDOWS = {"1D", "7D", "30D"}
SECOND_ORDER_ROWS = len(COUNTRIES) * 5 + len(ONE_YEAR_BOND_KEYS) + len(EXTENDED_BOND_KEYS)
BOND_CURVE_ROWS = len(COUNTRIES)
OHLC_MAX_WINDOW = 360


def main() -> int:
    if not SNAPSHOT.exists():
        print(f"FAIL missing snapshot: {SNAPSHOT}")
        return 1

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    html = HTML.read_text(encoding="utf-8") if HTML.exists() else ""
    quant_html = QUANT_HTML.read_text(encoding="utf-8") if QUANT_HTML.exists() else ""
    errors: list[str] = []

    country_names = {country["country"] for country in snapshot.get("countries", [])}
    if country_names != COUNTRIES:
        errors.append(f"countries mismatch: {sorted(country_names)}")

    for country in snapshot.get("countries", []):
        for field in FIELDS:
            cell = country.get(field)
            if not cell:
                errors.append(f"{country['country']} missing {field}")
                continue
            summary = cell.get("summary", {})
            if not summary.get("available"):
                errors.append(f"{country['country']} {field} unavailable")
            if summary.get("stale"):
                errors.append(f"{country['country']} {field} stale latest={summary.get('date')}")
            for change in CHANGES:
                if not summary.get(change):
                    errors.append(f"{country['country']} {field} missing {change}")

    vol_keys = set(snapshot.get("asset_class_vol", {}))
    if vol_keys != VOLS:
        errors.append(f"volatility groups mismatch: {sorted(vol_keys)}")
    for key in VOLS:
        item = snapshot.get("asset_class_vol", {}).get(key, {})
        if item.get("value") is None:
            errors.append(f"{key} volatility is null")
        if item.get("count", 0) <= 0:
            errors.append(f"{key} volatility has no samples")
        windows = item.get("windows", {})
        if set(windows) != VOL_WINDOWS:
            errors.append(f"{key} volatility windows mismatch: {sorted(windows)}")
        for window in VOL_WINDOWS:
            window_item = windows.get(window, {})
            if window_item.get("value") is None:
                errors.append(f"{key} {window} volatility is null")
            if window_item.get("count", 0) <= 0:
                errors.append(f"{key} {window} volatility has no samples")

    rankings = snapshot.get("volatility_rankings", {})
    if set(rankings) != VOLS:
        errors.append(f"volatility ranking groups mismatch: {sorted(rankings)}")
    for key in VOLS:
        rows = rankings.get(key, [])
        if len(rows) != VOL_RANKING_ROWS:
            errors.append(f"{key} volatility ranking row count mismatch: {len(rows)}")
        previous_7d = None
        for index, row in enumerate(rows, start=1):
            if row.get("rank") != index:
                errors.append(f"{key} volatility ranking bad rank: {row.get('rank')} expected {index}")
            if row.get("country") not in COUNTRIES:
                errors.append(f"{key} volatility ranking unknown country: {row.get('country')}")
            windows = row.get("windows", {})
            if set(windows) != VOL_WINDOWS:
                errors.append(f"{key} volatility ranking windows mismatch: {sorted(windows)}")
                continue
            for window in VOL_WINDOWS:
                if windows.get(window) is None:
                    errors.append(f"{key} {row.get('country')} {window} volatility ranking is null")
            current_7d = windows.get("7D")
            if current_7d is not None and previous_7d is not None and current_7d > previous_7d:
                errors.append(f"{key} volatility ranking not sorted by 7D desc")
            previous_7d = current_7d if current_7d is not None else previous_7d

    if '<section class="vol-grid">' in html:
        errors.append("top general volatility grid should not be rendered")
    if "波动率排名" not in html:
        errors.append("missing volatility ranking panel")
    if '<details class="panel volatility-panel">' not in html:
        errors.append("volatility ranking panel should be a collapsed details block")
    volatility_index = html.find("波动率排名")
    policy_index = html.find("政策新闻雷达")
    daily_alert_index = html.find("每日异动")
    if policy_index < 0:
        errors.append("missing policy news panel")
    elif volatility_index >= 0 and policy_index > volatility_index:
        errors.append("policy news panel should render before volatility ranking")
    if daily_alert_index < 0:
        errors.append("missing daily move alert panel")
    elif volatility_index >= 0 and daily_alert_index > volatility_index:
        errors.append("daily move alert should render before volatility ranking")
    daily_alert = snapshot.get("daily_move_alert", {})
    if daily_alert.get("window") != "30D":
        errors.append(f"daily move alert window mismatch: {daily_alert.get('window')}")
    if daily_alert.get("threshold_top_pct") != 20.0:
        errors.append(f"daily move alert threshold mismatch: {daily_alert.get('threshold_top_pct')}")
    if "items" not in daily_alert or "top_candidate" not in daily_alert:
        errors.append("daily move alert missing items/top_candidate keys")
    items = daily_alert.get("items") or []
    if daily_alert.get("shown_count") != len(items):
        errors.append("daily move alert shown_count should equal rendered item count")
    groups = [item.get("group") for item in items]
    for required_group in ["债券", "汇率"]:
        if required_group not in groups:
            errors.append(f"daily move alert missing fixed group: {required_group}")
    if groups.count("债券") > 1 or groups.count("汇率") > 1 or groups.count("股指") > 1:
        errors.append(f"daily move alert should show at most one row per group: {groups}")
    for item in items:
        for key in ["country", "group", "label", "move", "rank", "sample_count", "top_pct", "latest_date", "warning", "display_policy"]:
            if key not in item:
                errors.append(f"daily move alert item missing {key}")
        if item.get("group") in {"债券", "汇率"} and item.get("display_policy") != "固定显示":
            errors.append(f"daily move alert fixed group has wrong policy: {item.get('group')}")
        if item.get("group") == "股指":
            if item.get("display_policy") != "触发显示":
                errors.append("daily move alert equity should be trigger-only")
            if item.get("top_pct", 100) > daily_alert.get("threshold_top_pct", 20.0):
                errors.append("daily move alert equity item is outside threshold")
            if not item.get("warning"):
                errors.append("daily move alert equity item should be warning")
    forbidden_public_markers = [
        "sk-",
        "OPENAI_API_KEY",
        "BINANCE_",
        "API_KEY",
        "API_SECRET",
        "apiKey",
        "apiSecret",
        "base_usd",
        "base_configured",
        "trade_count",
        "BTCUSDT",
        "realizedPnl",
        "orderId",
        "quoteQty",
        "commission",
        "commissionAsset",
        "USDT+USDC",
        "option_usdt_value",
        "futures_usdc",
        "total_usdt_usdc",
        "option_positions",
        "futures_positions",
    ]
    if any(marker in html for marker in forbidden_public_markers):
        errors.append("HTML should not expose API keys or API key env names")
    if any(marker in quant_html for marker in forbidden_public_markers):
        errors.append("quant fund HTML should not expose API keys or private fields")
    snapshot_text = json.dumps(snapshot, ensure_ascii=False)
    if any(marker in snapshot_text for marker in forbidden_public_markers):
        errors.append("snapshot should not expose API keys")
    quant_fund = snapshot.get("quant_fund", {})
    if not quant_fund:
        errors.append("missing quant fund snapshot")
    for key in ["futures", "options", "equity"]:
        if key not in quant_fund:
            errors.append(f"missing quant fund section: {key}")
    if '<a class="quiet-quant-link" href="quant_fund.html">量化基金</a>' not in html:
        errors.append("missing quiet quant fund link in notes")
    if '<section class="panel quant-fund-detail">' in html:
        errors.append("main HTML should not render quant fund detail section")
    if '<section class="panel quant-fund-detail">' not in quant_html:
        errors.append("missing quant fund detail section page")
    if '<a class="quant-back" href="index.html">返回</a>' not in quant_html:
        errors.append("missing quant fund back link")
    for key in ["futures", "options", "equity"]:
        if f'<a class="quant-card" href="#quant-detail-{key}">' not in quant_html:
            errors.append(f"missing clickable quant fund card: {key}")
        if f'id="quant-detail-{key}"' not in quant_html:
            errors.append(f"missing quant fund detail panel: {key}")
    if "coming soon in 2026 3季度末" not in quant_html:
        errors.append("missing equity coming-soon copy")
    if (
        "本金已配置" in quant_html
        or "本金未配置" in quant_html
        or "等待本金" in quant_html
        or "历史种子" in quant_html
        or "百分比曲线" in quant_html
    ):
        errors.append("quant fund page should not spell out principal or percent-curve copy")
    if '<section class="panel quant-fund-bottom" id="quant-fund">' in html:
        errors.append("quant fund should not show as a default bottom panel")
    if '<a class="quant-fund-dock" href="#quant-fund">' in html:
        errors.append("quant fund should not be a fixed dock")
    if '<section class="quant-fund-page" id="quant-fund">' in html:
        errors.append("quant fund should not use a fixed overlay page")
    if '<details class="quant-fund-widget">' in html:
        errors.append("quant fund should not use the old expandable dock")
    for marker in ["期货", "期权"]:
        if marker in html:
            errors.append(f"main HTML should not render quant fund marker: {marker}")
    for marker in ["量化基金", "期货", "期权", "股指"]:
        if marker not in quant_html:
            errors.append(f"missing quant fund marker: {marker}")
    policy_news = snapshot.get("policy_news", {})
    if set(policy_news.get("regions", {})) != set(POLICY_REGIONS):
        errors.append(f"policy news regions mismatch: {sorted(policy_news.get('regions', {}))}")
    if policy_news.get("model") != "gpt-5.4-mini":
        errors.append(f"policy news model mismatch: {policy_news.get('model')}")
    for code, label in POLICY_REGIONS.items():
        region = policy_news.get("regions", {}).get(code, {})
        if region.get("name") != label:
            errors.append(f"policy news bad region label: {code} {region.get('name')}")
        if not region.get("items"):
            errors.append(f"policy news missing items: {code}")
        if not region.get("policy_tool"):
            errors.append(f"policy news missing policy tool: {code}")
        if "action_update_source" not in region:
            errors.append(f"policy news missing action update source: {code}")
        if "action_cache_status" not in region:
            errors.append(f"policy news missing action cache status: {code}")
        actions = region.get("actions", [])
        if not actions:
            errors.append(f"policy news missing rate actions: {code}")
        recent_year_actions = region.get("recent_year_actions", [])
        if not isinstance(recent_year_actions, list):
            errors.append(f"policy news recent-year actions should be a list: {code}")
        for action in actions:
            if action.get("type") not in {"加息", "降息"}:
                errors.append(f"policy news bad action type: {code} {action.get('type')}")
            if not action.get("date") or not action.get("rate_after") or "change_bp" not in action:
                errors.append(f"policy news incomplete action: {code} {action}")
        if label not in html:
            errors.append(f"policy news region label missing from HTML: {label}")
    for marker in [
        'class="policy-actions"',
        "实际操作",
        "政策工具",
        "查看近一年实际操作",
        "policy-actions-expanded",
        "每周更新 / OpenAI 5.4 mini",
        "新闻态度每周自动更新",
        "action_cache_status",
        "2025-12-11",
        "2026-06-17",
    ]:
        if marker not in html:
            snapshot_text = json.dumps(snapshot, ensure_ascii=False)
            if marker not in snapshot_text:
                errors.append(f"missing policy action marker: {marker}")
    inline_vol_count = html.count('class="asset-vol"')
    if inline_vol_count != DERIVATIVE_VOL_COUNT:
        errors.append(f"inline asset volatility count mismatch: {inline_vol_count}")
    derivative_section = html.split('<table class="derivative-table">', 1)[-1].split("</table>", 1)[0]
    market_section = html.split('<table class="market-table">', 1)[-1].split("</table>", 1)[0]
    derivative_vol_count = derivative_section.count('class="asset-vol"')
    market_vol_count = market_section.count('class="asset-vol"')
    if derivative_vol_count != DERIVATIVE_VOL_COUNT:
        errors.append(f"derivative table volatility count mismatch: {derivative_vol_count}")
    if market_vol_count != 0:
        errors.append(f"market panel should not render inline volatility: {market_vol_count}")
    for marker in ["renderBondCurveChart", "curve-positive-band", "curve-negative-band"]:
        if marker not in html:
            errors.append(f"missing bond curve chart marker: {marker}")
    for marker in ['const defaultOhlcKey = "US_10Y"', 'render(defaultOhlcKey, { scroll: false })']:
        if marker not in html:
            errors.append(f"missing default OHLC marker: {marker}")
    for marker in [
        'class="ohlc-toolbar"',
        'class="ohlc-mode active"',
        'data-mode="move"',
        "renderMoveChart",
        "涨跌幅模式",
        'data-window="90"',
        'data-window="180"',
        'data-window="360"',
        "setVisibleWindow",
        "zoomChart",
        "dragStart",
        'id="ohlc-start-date"',
        'id="ohlc-end-date"',
        'id="ohlc-jump-date"',
        "customRangeByKey",
        "applyOhlcRange",
        "jumpToOhlcDate",
        'id="spread-panel"',
        'id="spread-country-select"',
        'id="spread-start-date"',
        'id="spread-exact-date"',
        'id="spread-data"',
        "buildSpreadRows",
        "renderSpread",
        "spread-positive-band",
        "spread-negative-band",
        "spread-long-line",
        "spread-short-line",
        "data-spread-window=\"1\"",
        "data-spread-window=\"7\"",
        "data-spread-window=\"30\"",
    ]:
        if marker not in html:
            errors.append(f"missing OHLC interaction marker: {marker}")
    for marker in [
        'class="country-toggle expanded"',
        'class="country-toggle collapsed"',
        'data-country="美国"',
        'data-country="日本"',
        'data-extra-bond-toggle="美国"',
        'data-extra-bond-row="true"',
        "extraBondToggles",
        "toggleCountryRows",
    ]:
        if marker not in html:
            errors.append(f"missing second-order country accordion marker: {marker}")

    second_order = snapshot.get("second_order_monitor", [])
    if len(second_order) != SECOND_ORDER_ROWS:
        errors.append(f"second order row count mismatch: {len(second_order)}")
    row_by_key = {row.get("key"): row for row in second_order}
    for key, country in ONE_YEAR_BOND_KEYS.items():
        row = row_by_key.get(key)
        if not row:
            errors.append(f"missing 1Y bond second-order row: {key}")
            continue
        if row.get("country") != country or row.get("group") != "债券":
            errors.append(f"bad 1Y bond row placement: {key} {row.get('country')} {row.get('group')}")
        if f'data-ohlc-key="{key}"' not in html:
            errors.append(f"missing 1Y bond OHLC row marker: {key}")
    for key, country in EXTENDED_BOND_KEYS.items():
        row = row_by_key.get(key)
        if not row:
            errors.append(f"missing extended bond second-order row: {key}")
            continue
        if row.get("country") != country or row.get("group") != "债券":
            errors.append(f"bad extended bond row placement: {key} {row.get('country')} {row.get('group')}")
        if not row.get("extra_bond"):
            errors.append(f"extended bond row should be marked extra: {key}")
        if f'data-ohlc-key="{key}"' not in html:
            errors.append(f"missing extended bond OHLC row marker: {key}")
    curve_rows = [row for row in second_order if row.get("group") == "债券曲线"]
    if len(curve_rows) != BOND_CURVE_ROWS:
        errors.append(f"bond curve row count mismatch: {len(curve_rows)}")
    for row in second_order:
        metrics = row.get("metrics", {})
        if set(metrics) != SECOND_ORDER_WINDOWS:
            errors.append(f"{row.get('country')} {row.get('label')} second order windows mismatch: {sorted(metrics)}")
        for window in SECOND_ORDER_WINDOWS:
            metric = metrics.get(window)
            if not metric:
                errors.append(f"{row.get('country')} {row.get('label')} missing {window} derivative")
                continue
            for key in ["velocity", "previous_velocity", "acceleration", "signal"]:
                if key not in metric:
                    errors.append(f"{row.get('country')} {row.get('label')} {window} missing {key}")
        ohlc = row.get("ohlc") or []
        if not ohlc:
            errors.append(f"{row.get('country')} {row.get('label')} missing OHLC rows")
        if row.get("key") == "US_10Y" and len(ohlc) < OHLC_MAX_WINDOW:
            errors.append(f"US_10Y default OHLC has fewer than {OHLC_MAX_WINDOW} rows: {len(ohlc)}")
        for bar in ohlc:
            for key in ["date", "open", "high", "low", "close"]:
                if key not in bar:
                    errors.append(f"{row.get('country')} {row.get('label')} OHLC missing {key}")
                    break
        if len(ohlc) > 1 and not any("change_pct" in bar for bar in ohlc):
            errors.append(f"{row.get('country')} {row.get('label')} OHLC missing daily percent moves")
        if row.get("group") == "债券曲线":
            if row.get("chart_type") != "bond_curve":
                errors.append(f"{row.get('country')} bond curve missing chart_type")
            curve = row.get("curve") or {}
            curve_data = curve.get("rows") or []
            if len(curve_data) < 30:
                errors.append(f"{row.get('country')} bond curve has too few paired rows: {len(curve_data)}")
            if row.get("key") == "US_10Y2Y" and len(curve_data) < OHLC_MAX_WINDOW:
                errors.append(f"US_10Y2Y curve has fewer than {OHLC_MAX_WINDOW} rows: {len(curve_data)}")
            if not curve.get("bond_2y_label") or not curve.get("bond_10y_label"):
                errors.append(f"{row.get('country')} bond curve missing component labels")
            for item in curve_data:
                for key in ["date", "bond_2y", "bond_10y", "spread_bp", "positive"]:
                    if key not in item:
                        errors.append(f"{row.get('country')} bond curve paired row missing {key}")
                        break
                if {"bond_2y", "bond_10y", "spread_bp", "positive"} <= set(item):
                    expected_spread = (item["bond_10y"] - item["bond_2y"]) * 100
                    if abs(item["spread_bp"] - expected_spread) > 1e-7:
                        errors.append(f"{row.get('country')} bond curve bad spread calculation")
                    if item["positive"] != (item["bond_10y"] >= item["bond_2y"]):
                        errors.append(f"{row.get('country')} bond curve bad positive flag")

    flow_names = {section["name"] for section in snapshot.get("fx_flows", [])}
    if flow_names != FLOWS:
        errors.append(f"flow groups mismatch: {sorted(flow_names)}")
    for section in snapshot.get("fx_flows", []):
        period_names = {period["period"] for period in section.get("periods", [])}
        if period_names != PERIODS:
            errors.append(f"{section['name']} periods mismatch: {sorted(period_names)}")
        for period in section.get("periods", []):
            result = period.get("result") or {}
            if not result.get("best_route"):
                errors.append(f"{section['name']} {period['period']} missing best route: {period.get('missing')}")
            if result.get("source_code") != USER_FX_FLOW_CODE:
                errors.append(f"{section['name']} {period['period']} not using user FX flow code")
            routes = result.get("routes", [])
            if routes and len(routes) != 6:
                errors.append(f"{section['name']} {period['period']} route count mismatch: {len(routes)}")
    expected_flow_routes = len(FLOWS) * len(PERIODS) * 6
    flow_route_count = html.count('class="flow-route"')
    if flow_route_count != expected_flow_routes:
        errors.append(f"flow route button count mismatch: {flow_route_count}")
    collapsed_route_groups = html.count('class="flow-routes" hidden')
    if collapsed_route_groups != FLOW_PERIOD_COUNT:
        errors.append(f"collapsed flow route group count mismatch: {collapsed_route_groups}")
    flow_expand_count = html.count('class="flow-expand"')
    if flow_expand_count != FLOW_PERIOD_COUNT:
        errors.append(f"flow route expand button count mismatch: {flow_expand_count}")
    if 'class="flow-grid" data-flow-panel-body hidden' not in html:
        errors.append("FX flow panel should be collapsed by default")
    for marker in [
        'id="fx-flow-data"',
        'data-flow-panel-toggle',
        'data-flow-panel-body',
        "toggleFlowPanel",
        ".flow-routes[hidden]",
        ".flow-route-detail",
        ".flow-route-detail[hidden]",
        ".flow-calc-more[hidden]",
        "toggleFlowRoutes",
        "toggleFlowCalculation",
        "renderFlowDetail",
        "collapseFlowDetail",
        "activeFlowRouteKey",
        "createFlowDetail",
        'insertAdjacentElement("afterend", flowDetail)',
        "directTerm",
        "new / old",
        "ln(new / old)",
        "100 * ln(new / old)",
        "Q(",
        "score =",
    ]:
        if marker not in html:
            errors.append(f"missing FX flow detail marker: {marker}")
    if "flowDetail?.scrollIntoView" in html:
        errors.append("FX flow detail should expand in place without auto scrolling")
    if 'id="flow-detail"' in html or 'id="flow-detail-body"' in html:
        errors.append("FX flow detail should be inserted under the clicked route, not rendered as a global panel")
    hedge_markers = [
        'class="panel hedge-cycle-panel"',
        "长短债 8 种对冲",
        "降息周期",
        "加息周期",
        "前两种偏缩，后两种偏扩",
        "第一次加息常见长短债交叉",
    ]
    for marker in hedge_markers:
        if marker not in html:
            errors.append(f"missing hedge cycle marker: {marker}")
    hedge_case_count = html.count('class="hedge-case"')
    if hedge_case_count != 8:
        errors.append(f"hedge case count mismatch: {hedge_case_count}")
    hedge_index = html.find('class="panel hedge-cycle-panel"')
    status_panel = '<details class="panel status-panel">'
    if status_panel not in html:
        errors.append("data status panel should be a collapsed details block")
    if '<details class="panel status-panel" open' in html:
        errors.append("data status panel should default collapsed")
    status_index = html.find(status_panel)
    if hedge_index < 0 or status_index < 0 or hedge_index > status_index:
        errors.append("hedge cycle panel should render before data status")
    hike_example_markers = [
        'class="hike-example"',
        "2022 加息周期长短债例子",
        "US2YR.OTC / US10YR.OTC 本地日线",
        "短低长高",
        "短低长低",
        "短高长低",
        "短高长高",
        "2022-03-16 首次加息",
    ]
    for marker in hike_example_markers:
        if marker not in html:
            errors.append(f"missing hike cycle example marker: {marker}")
    hike_phase_count = html.count('class="hike-phase"')
    if hike_phase_count != 4:
        errors.append(f"hike phase count mismatch: {hike_phase_count}")
    hike_phase_chart_count = html.count('class="hike-phase-chart"')
    if hike_phase_chart_count != 8:
        errors.append(f"hike phase chart count mismatch: {hike_phase_chart_count}")
    for marker in [
        "10Y：2020-07 到 2021-03",
        "2Y：2020-07 到 2021-03",
        "10Y：2021-01 到 2021-07",
        "2Y：2021-06 到 2021-08",
        "10Y：2021-08 到 2022-02",
        "2Y：2021-08 到 2022-02",
        "10Y：2022-02 到 2022-06",
        "2Y：2022-02 到 2022-06",
    ]:
        if marker not in html:
            errors.append(f"missing hike focused chart marker: {marker}")
    if "2021-08=100" in html:
        errors.append("hike phase charts should not render indexed changes")
    hike_chart_label_count = html.count('class="hike-chart-label"')
    if hike_chart_label_count < 8:
        errors.append(f"hike chart label count mismatch: {hike_chart_label_count}")
    if 'class="hike-overview-legend"' not in html:
        errors.append("missing external hike overview legend")
    if 'class="hike-event-note"' not in html:
        errors.append("missing external hike event note")
    if 'class="hike-legend"' in html:
        errors.append("hike overview legend should not be rendered inside the SVG")
    if 'class="hike-event-label"' in html:
        errors.append("hike first-hike label should not be rendered inside the SVG")

    notes = "\n".join(snapshot.get("notes", []))
    if "derived = 本地公式" not in notes:
        errors.append("missing derived source explanation note")
    if "RUB 交叉汇率优先使用具备历史深度的 Yahoo 直接报价" not in notes:
        errors.append("missing RUB direct source policy note")

    status_by_key = {item.get("key"): item for item in snapshot.get("series_status", [])}
    if status_by_key.get("JP_EQUITY", {}).get("source") != "nikkei":
        errors.append(f"JP_EQUITY should use official Nikkei source, got {status_by_key.get('JP_EQUITY', {}).get('source')}")
    for key, direct_key in [("RUBCNY", "RUBCNY_YAHOO"), ("RUBJPY", "RUBJPY_YAHOO")]:
        selected = status_by_key.get(key, {})
        direct = status_by_key.get(direct_key, {})
        if direct and not direct.get("stale") and direct.get("count", 0) >= 30 and selected.get("source") != "yahoo":
            errors.append(f"{key} should prefer fresh direct Yahoo source, got {selected.get('source')}")

    audit = {item.get("key"): item for item in snapshot.get("source_audit", [])}
    for key in ["CNY_BASE", "CNYJPY", "US_10Y2Y", "CN_10Y2Y", "JP_10Y2Y", "DE_10Y2Y", "RU_10Y2Y", "KR_10Y2Y"]:
        if key not in audit:
            errors.append(f"missing source audit row: {key}")
    for key in ["RUBCNY", "RUBJPY"]:
        item = audit.get(key)
        if not item:
            errors.append(f"missing source audit row: {key}")
            continue
        if item.get("selected_source") == "yahoo":
            comparison = item.get("comparison")
            if not comparison:
                errors.append(f"{key} missing direct/formula comparison")
            elif abs(comparison.get("pct_diff", 100)) > 2:
                errors.append(f"{key} direct/formula comparison diverges: {comparison.get('pct_diff')}")

    if errors:
        print("VALIDATION FAIL")
        for error in errors:
            print("ERROR", error)
        return 1

    print("VALIDATION PASS")
    print(f"generated_at {snapshot.get('generated_at')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
