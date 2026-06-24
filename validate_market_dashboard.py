#!/usr/bin/env python3
"""Validate that the generated market dashboard satisfies the requested coverage."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


SNAPSHOT = Path(__file__).resolve().parent / "dashboard" / "latest_market_snapshot.json"
HTML = Path(__file__).resolve().parent / "dashboard" / "index.html"
DEFAULT_FX_FLOW_CODE = Path(__file__).resolve().parent / "fx_flow_logic.py"
USER_FX_FLOW_CODE = str(Path(os.environ.get("FX_FLOW_CODE_PATH", str(DEFAULT_FX_FLOW_CODE))))
COUNTRIES = {"美国", "中国", "日本", "德国", "俄罗斯", "韩国"}
FIELDS = ["bond_2y", "bond_10y", "equity", "fx"]
CHANGES = ["chg_1d", "chg_7d", "chg_14d", "chg_30d"]
FLOWS = {"中日美", "中德美", "中俄美"}
PERIODS = {"当日", "上日", "当周", "上周", "当月", "上月"}
VOLS = {"equity", "bond", "fx"}
VOL_WINDOWS = {"7D", "30D"}
VOL_RANKING_ROWS = 6
INLINE_VOL_COUNT = len(COUNTRIES) * len(FIELDS)
SECOND_ORDER_WINDOWS = {"1D", "7D", "30D"}
SECOND_ORDER_ROWS = 30
BOND_CURVE_ROWS = len(COUNTRIES)


def main() -> int:
    if not SNAPSHOT.exists():
        print(f"FAIL missing snapshot: {SNAPSHOT}")
        return 1

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    html = HTML.read_text(encoding="utf-8") if HTML.exists() else ""
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
    inline_vol_count = html.count('class="asset-vol"')
    if inline_vol_count != INLINE_VOL_COUNT:
        errors.append(f"inline asset volatility count mismatch: {inline_vol_count}")
    for marker in ["renderBondCurveChart", "curve-positive-band", "curve-negative-band"]:
        if marker not in html:
            errors.append(f"missing bond curve chart marker: {marker}")

    second_order = snapshot.get("second_order_monitor", [])
    if len(second_order) != SECOND_ORDER_ROWS:
        errors.append(f"second order row count mismatch: {len(second_order)}")
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
        for bar in ohlc:
            for key in ["date", "open", "high", "low", "close"]:
                if key not in bar:
                    errors.append(f"{row.get('country')} {row.get('label')} OHLC missing {key}")
                    break
        if row.get("group") == "债券曲线":
            if row.get("chart_type") != "bond_curve":
                errors.append(f"{row.get('country')} bond curve missing chart_type")
            curve = row.get("curve") or {}
            curve_data = curve.get("rows") or []
            if len(curve_data) < 30:
                errors.append(f"{row.get('country')} bond curve has too few paired rows: {len(curve_data)}")
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
