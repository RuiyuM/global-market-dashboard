"""Join closed three-currency routes to later local bond and equity closes."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import permutations
from math import ceil, isfinite
from typing import Any

from fx_flow_logic import calc_q


MARKETS = {
    "US": ("美", "美国", "标普500"),
    "CN": ("中", "中国", "上证综指"),
    "JP": ("日", "日本", "日经225"),
    "DE": ("德", "德国（欧元代理）", "DAX"),
    "RU": ("俄", "俄罗斯", "MOEX"),
}
TRIADS = {
    "JP": ("中日美", {("US", "CN"): "USDCNY", ("JP", "CN"): "JPYCNY", ("US", "JP"): "USDJPY"}),
    "DE": ("中德美", {("US", "CN"): "USDCNY", ("DE", "CN"): "EURCNY", ("DE", "US"): "EURUSD"}),
    "RU": ("中俄美", {("US", "CN"): "USDCNY", ("RU", "CN"): "RUBCNY", ("US", "RU"): "USDRUB"}),
}
TENOR_GROUPS = {
    "short": ("1M", "3M", "6M", "1Y"),
    "mid": ("2Y", "3Y", "5Y", "7Y"),
    "long": ("10Y", "30Y"),
}
WEEK = timedelta(days=7)
BASKET_LOOKBACK = timedelta(days=90)
MAX_REFERENCE_GAP = timedelta(days=7)
MAX_BOND_WAIT = timedelta(days=14)
MAX_STOCK_BASE_WAIT = timedelta(days=7)
HORIZON_LIMITS = {1: timedelta(days=7), 5: timedelta(days=14)}
WINDOW_LIMIT = 10
EPSILON = 1e-9


def _closed_quotes(rows: list[dict[str, Any]], through: date, *, positive: bool = False) -> dict[date, float]:
    result = {}
    for row in rows:
        try:
            day = row["date"]
            if isinstance(day, str):
                day = date.fromisoformat(day)
            elif isinstance(day, datetime):
                day = day.date()
            value = float(row["close"])
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
        if isinstance(day, date) and day.weekday() < 5 and day <= through and isfinite(value):
            if value > 0 or not positive:
                result[day] = value
    return result


def _window_pairs(days: list[date], cutoff: date) -> dict[str, list[tuple[date, date]]]:
    recent = days[-WINDOW_LIMIT - 1 :]
    daily = list(zip(recent, recent[1:]))
    week_closes = {}
    for day in days:
        friday = day + timedelta(days=4 - day.weekday())
        # Do not treat a Monday or Tuesday last available quote as a week-end close.
        if friday <= cutoff and friday - day <= timedelta(days=2):
            week_closes[friday] = day
    weekly = [
        (week_closes[friday - WEEK], day)
        for friday, day in week_closes.items()
        if friday - WEEK in week_closes
    ]
    return {"daily": daily[::-1], "weekly": weekly[-WINDOW_LIMIT:][::-1]}


def _route_labels(third: str) -> list[dict[str, str]]:
    return [
        {
            "id": f"{origin}-{via}-{destination}",
            "label": "→".join(MARKETS[currency][0] for currency in (origin, via, destination)),
            "origin": origin,
            "via": via,
            "destination": destination,
        }
        for origin, via, destination in permutations(("US", "CN", third))
    ]


def _baskets(
    curves: dict[str, dict[date, float]], signal: date,
) -> dict[str, list[str]]:
    first = signal - BASKET_LOOKBACK
    dates = {tenor: {day for day in quotes if first <= day <= signal} for tenor, quotes in curves.items()}
    union = set().union(*dates.values())
    minimum = max(1, ceil(len(union) * 0.8))
    selected = {}
    for group, tenors in TENOR_GROUPS.items():
        covered = [tenor for tenor in tenors if dates.get(tenor)]
        eligible = [tenor for tenor in covered if len(dates[tenor]) >= minimum]
        selected[group] = eligible or ([max(covered, key=lambda tenor: len(dates[tenor]))] if covered else [])
    return selected


def _bond_observation(
    curves: dict[str, dict[date, float]], signal: date, as_of: date,
) -> dict[str, Any]:
    baskets = _baskets(curves, signal)
    members = [tenor for tenors in baskets.values() for tenor in tenors]
    shared_dates = []
    if baskets["mid"] and baskets["long"]:
        shared_dates = sorted(set.intersection(*(set(curves[tenor]) for tenor in members)))
    base = next((day for day in reversed(shared_dates) if signal - MAX_REFERENCE_GAP <= day <= signal), None)
    deadline = signal + MAX_BOND_WAIT
    observed = next((day for day in shared_dates if signal < day <= deadline), None) if base else None
    if observed:
        status = "available"
    elif base and as_of <= deadline:
        status = "pending"
    else:
        status = "unavailable"

    groups = {}
    for group, tenors in baskets.items():
        before = sum(curves[tenor][base] for tenor in tenors) / len(tenors) if tenors and base else None
        after = sum(curves[tenor][observed] for tenor in tenors) / len(tenors) if tenors and observed else None
        groups[group] = {
            "status": status if tenors else "unavailable",
            "tenors": tenors,
            "base_yield": before,
            "yield": after,
            "change_bp": 100 * (after - before) if before is not None and after is not None else None,
        }
    return {
        "status": status,
        "base_date": base.isoformat() if base else None,
        "date": observed.isoformat() if observed else None,
        "groups": groups,
    }


def _equity_observation(
    label: str, quotes: dict[date, float], bond: dict[str, Any], as_of: date,
) -> dict[str, Any]:
    later = []
    status = bond["status"]
    if bond["date"]:
        bond_day = date.fromisoformat(bond["date"])
        later = sorted(day for day in quotes if bond_day < day)
        deadline = bond_day + MAX_STOCK_BASE_WAIT
        if not later or later[0] > deadline:
            status = "pending" if quotes and as_of <= deadline else "unavailable"
            later = []

    base = later[0] if later else None
    horizons = {}
    for sessions, max_window in HORIZON_LIMITS.items():
        target = later[sessions] if len(later) > sessions else None
        outcome = {"status": status, "date": None, "value": None, "return_pct": None}
        if base:
            deadline = base + max_window
            if target and target <= deadline:
                outcome = {
                    "status": "available",
                    "date": target.isoformat(),
                    "value": quotes[target],
                    "return_pct": 100 * (quotes[target] / quotes[base] - 1),
                }
            else:
                outcome["status"] = "pending" if as_of <= deadline else "unavailable"
        horizons[str(sessions)] = outcome

    return {
        "status": status,
        "label": label,
        "base_date": base.isoformat() if base else None,
        "base_value": quotes[base] if base else None,
        "horizons": horizons,
    }


def _score_window(
    base: date,
    signal: date,
    pair_keys: dict[tuple[str, str], str],
    fx: dict[str, dict[date, float]],
    routes: list[dict[str, str]],
    observations: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    direct = {}
    for (origin, destination), key in pair_keys.items():
        change = calc_q(fx[key][base], fx[key][signal])
        direct[origin, destination] = change
        direct[destination, origin] = -change

    ranked = []
    for route in routes:
        origin, via, destination = route["origin"], route["via"], route["destination"]
        score = direct[origin, via] + direct[via, destination]
        comparator = direct[origin, destination]
        bond, equity = observations[destination]
        ranked.append({
            **route,
            "score": score,
            "direct": comparator,
            "residual": score - comparator,
            "bond": bond,
            "equity": equity,
        })
    ranked.sort(key=lambda route: route["score"], reverse=True)
    rank = 1
    for index, route in enumerate(ranked):
        if ranked[rank - 1]["score"] - route["score"] > EPSILON:
            rank = index + 1
        route["rank"] = rank

    return {
        "base_date": base.isoformat(),
        "signal_date": signal.isoformat(),
        "best_route_id": ranked[0]["id"] if ranked[0]["score"] > EPSILON else None,
        "routes": ranked,
    }


def build_route_market_tracker(
    series: dict[str, list[dict[str, Any]]], *, cutoff_date: date, as_of_date: date,
) -> dict[str, Any]:
    """Use NY-closed FX dates and caller-confirmed completed local quote dates."""
    cutoff = min(cutoff_date, as_of_date)
    fx_keys = {key for _, pairs in TRIADS.values() for key in pairs.values()}
    fx = {key: _closed_quotes(series.get(key, []), cutoff, positive=True) for key in fx_keys}
    equities = {country: _closed_quotes(series.get(f"{country}_EQUITY", []), as_of_date, positive=True) for country in MARKETS}
    curves = {
        country: {
            tenor: _closed_quotes(series.get(f"{country}_{tenor}", []), as_of_date)
            for tenors in TENOR_GROUPS.values() for tenor in tenors
        }
        for country in MARKETS
    }
    outcomes = {}
    groups = []
    for country, (label, pairs) in TRIADS.items():
        routes = _route_labels(country)
        days = sorted(set.intersection(*(set(fx[key]) for key in pairs.values())))
        group = {"id": country, "label": label, "routes": routes}
        for period, windows in _window_pairs(days, cutoff).items():
            group[period] = []
            for base, signal in windows:
                observations = {}
                for destination in ("US", "CN", country):
                    key = (destination, signal)
                    if key not in outcomes:
                        bond = _bond_observation(curves[destination], signal, as_of_date)
                        equity = _equity_observation(MARKETS[destination][2], equities[destination], bond, as_of_date)
                        outcomes[key] = (bond, equity)
                    observations[destination] = outcomes[key]
                group[period].append(_score_window(base, signal, pairs, fx, routes, observations))
        groups.append(group)

    return {
        "version": 1,
        "as_of_date": as_of_date.isoformat(),
        "cutoff_date": cutoff.isoformat(),
        "markets": {
            country: {"label": label, "equity_label": equity}
            for country, (_, label, equity) in MARKETS.items()
        },
        "groups": groups,
    }
