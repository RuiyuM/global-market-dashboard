"""Summarize the selected destination's cash-flow and price evidence."""

from __future__ import annotations

from math import isfinite
from typing import Any


BOND_MOVE_FLOOR_BP = 1.0
OFFICIAL_HEADLINES = {
    "debt": "净买入偏向债券",
    "equity": "净买入偏向股票及基金",
    "both": "债券、股票及基金均获净买入",
    "neither": "债券、股票及基金均未见净买入",
}
PRICE_HEADLINES = {
    "debt": "价格偏债券",
    "equity": "价格偏股指",
    "both": "股债价格都偏强",
    "neither": "股债价格均未见明显走强",
    "mixed": "价格线索分化",
    "unknown": "暂不能判断",
}


def _number(value: Any) -> int | float | None:
    if type(value) is int or (type(value) is float and isfinite(value)):
        return value
    return None


def _signed(value: int | float, unit: str, precision: int = 2) -> str:
    if isinstance(value, int):
        return f"{value:+,}{unit}" if value else f"0{unit}"
    rounded = round(value, precision)
    if not rounded:
        return f"0{unit}"
    return f"{rounded:+,.{precision}f}".rstrip("0").rstrip(".") + unit


def _official_assessment(route: dict[str, Any]) -> dict[str, Any] | None:
    flow = route.get("flow") or {}
    if route.get("destination") != "JP" or flow.get("status") != "published":
        return None
    short, long, equity = (_number(flow.get(key)) for key in ("short_net", "long_net", "equity_net"))
    if short is None or long is None or equity is None:
        return None
    debt = short + long
    if debt > 0 and equity > 0:
        code = "both"
    elif debt > 0:
        code = "debt"
    elif equity > 0:
        code = "equity"
    else:
        code = "neither"
    unit = " 亿日元"
    debt_detail = f"{_signed(debt, unit)}（短债 {_signed(short, '')}，中长期债 {_signed(long, '')}）"
    details = [
        {"label": "债券净买入合计", "value": debt_detail},
        {"label": "股票及基金净买入", "value": _signed(equity, unit)},
    ]
    if flow.get("week_start") and flow.get("week_end"):
        details.append({"label": "统计周", "value": f"{flow['week_start']} 至 {flow['week_end']}"})
    return {
        "kind": "official", "code": code, "headline": OFFICIAL_HEADLINES[code],
        "explanation": "日本财务省周报统计非居民对日本发行证券的净交易。债券含国债和其他债券，数据无法追踪到某条汇率路径或某个股指。",
        "details": details,
    }


def _bond_evidence(bond: dict[str, Any]) -> tuple[str, str]:
    groups = bond.get("groups") or {}
    mid, long = (groups.get(key) or {} for key in ("mid", "long"))
    mid_change = _number(mid.get("change_bp")) if mid.get("status") == "available" else None
    long_change = _number(long.get("change_bp")) if long.get("status") == "available" else None
    if mid_change is None or long_change is None:
        if bond.get("status") == "pending":
            return "pending", "等待下一次完整债券观察"
        return "unavailable", "中长端数据不足"

    mid_move, long_move = round(mid_change, 8), round(long_change, 8)
    changes = f"中端收益率 {_signed(mid_change, ' bp')}，长端 {_signed(long_change, ' bp')}"
    if mid_move <= -BOND_MOVE_FLOOR_BP and long_move <= -BOND_MOVE_FLOOR_BP:
        return "up", f"债价偏强（{changes}）"
    if mid_move >= BOND_MOVE_FLOOR_BP and long_move >= BOND_MOVE_FLOOR_BP:
        return "down", f"债价承压（{changes}）"
    if max(abs(mid_move), abs(long_move)) < BOND_MOVE_FLOOR_BP:
        return "flat", f"变化较小（{changes}）"
    return "mixed", f"尚无一致方向（{changes}）"


def _equity_evidence(equity: dict[str, Any]) -> tuple[str, str, str]:
    horizons = equity.get("horizons") or {}
    first, fifth = (horizons.get(key) or {} for key in ("1", "5"))
    one = _number(first.get("return_pct")) if first.get("status") == "available" else None
    five = _number(fifth.get("return_pct")) if fifth.get("status") == "available" else None
    if one is None and five is None:
        if first.get("status") == "pending" or fifth.get("status") == "pending" or equity.get("status") == "pending":
            return "pending", "等待后续股指收盘", ""
        return "unavailable", "暂无可用的后续股指收盘", ""

    display = []
    if one is not None:
        display.append(f"后 1 日 {_signed(one, '%')}")
    if five is not None:
        display.append(f"后 5 日 {_signed(five, '%')}")
    if one is not None and five is not None and round(one, 2) * round(five, 2) < 0:
        return "mixed", "，".join(display), "后 1 日与后 5 日方向相反。"
    if five is None:
        display.append("后 5 日待观察" if fifth.get("status") == "pending" else "后 5 日暂无数据")
    chosen = round(five if five is not None else one, 2)
    state = "up" if chosen > 0 else "down" if chosen < 0 else "flat"
    return state, "，".join(display), "目前仅按后 1 日初判。" if five is None else "股指以随后 5 个收盘的涨跌为主。"


def assess_route_market(route: dict[str, Any]) -> dict[str, Any]:
    official = _official_assessment(route)
    if official is not None:
        return official

    bond_state, bond_text = _bond_evidence(route.get("bond") or {})
    equity = route.get("equity") or {}
    equity_state, equity_text, horizon_note = _equity_evidence(equity)
    details = [
        {"label": "债券", "value": bond_text},
        {"label": equity.get("label") or "股指", "value": equity_text},
    ]
    if {bond_state, equity_state} & {"pending", "unavailable"}:
        detail = "债券或股指观察尚未齐备。"
        flow = route.get("flow") or {}
        if flow.get("status") == "pending":
            detail += "净买入周报待发布。"
        else:
            detail += "本期也暂无净买入统计可核对。"
        return {
            "kind": "waiting", "code": "unknown", "headline": PRICE_HEADLINES["unknown"],
            "explanation": detail, "details": details,
        }

    if "mixed" in {bond_state, equity_state}:
        code = "mixed"
    elif bond_state == equity_state == "up":
        code = "both"
    elif bond_state == "up":
        code = "debt"
    elif equity_state == "up":
        code = "equity"
    else:
        code = "neither"
    note = "价格线索显示哪个市场较强，确认资金去向还需成交统计。"
    if bond_state == "mixed":
        note += "中长端收益率没有同向变动至少 1 bp。"
    return {
        "kind": "price", "code": code, "headline": PRICE_HEADLINES[code],
        "explanation": note + horizon_note, "details": details,
    }


def attach_route_market_assessments(payload: dict[str, Any]) -> None:
    for group in payload.get("groups", []):
        for frequency in ("daily", "weekly"):
            for window in group.get(frequency, []):
                for route in window.get("routes", []):
                    route["assessment"] = assess_route_market(route)
