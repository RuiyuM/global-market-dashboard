#!/usr/bin/env python3
"""Validate that the generated market dashboard satisfies the requested coverage."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


SNAPSHOT = Path(__file__).resolve().parent / "dashboard" / "latest_market_snapshot.json"
DEFAULT_FX_FLOW_CODE = Path(__file__).resolve().parent / "fx_flow_logic.py"
USER_FX_FLOW_CODE = str(Path(os.environ.get("FX_FLOW_CODE_PATH", str(DEFAULT_FX_FLOW_CODE))))
COUNTRIES = {"美国", "中国", "日本", "德国", "俄罗斯", "韩国"}
FIELDS = ["bond_2y", "bond_10y", "equity", "fx"]
CHANGES = ["chg_1d", "chg_7d", "chg_14d", "chg_30d"]
FLOWS = {"中日美", "中德美", "中俄美"}
PERIODS = {"当日", "当周", "当月"}
VOLS = {"equity", "bond", "fx"}
SECOND_ORDER_WINDOWS = {"1D", "7D", "30D"}
SECOND_ORDER_ROWS = 30


def main() -> int:
    if not SNAPSHOT.exists():
        print(f"FAIL missing snapshot: {SNAPSHOT}")
        return 1

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
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

    second_order = snapshot.get("second_order_monitor", [])
    if len(second_order) != SECOND_ORDER_ROWS:
        errors.append(f"second order row count mismatch: {len(second_order)}")
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
