#!/usr/bin/env python3
"""Tests for automated official policy-rate action extraction."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import policy_rates
from policy_rates import (
    PolicyRatePoint,
    actions_from_rate_points,
    build_policy_actions,
    fetch_boj_points,
    fetch_china_lpr_points,
    parse_ecb_points,
    parse_boj_statement_points,
    parse_china_lpr_points,
    parse_fed_points,
    parse_fed_all_points,
    parse_korea_base_rate_points,
    parse_russia_points,
    split_default_and_recent_year,
)


def test_actions_from_rate_points_detects_hikes_and_cuts() -> None:
    points = [
        PolicyRatePoint("US", date(2025, 9, 18), "4.00-4.25%", 4.25, "Fed", "https://example.com/fed"),
        PolicyRatePoint("US", date(2025, 10, 30), "3.75-4.00%", 4.00, "Fed", "https://example.com/fed"),
        PolicyRatePoint("US", date(2025, 12, 11), "3.50-3.75%", 3.75, "Fed", "https://example.com/fed"),
        PolicyRatePoint("US", date(2026, 3, 18), "4.00-4.25%", 4.25, "Fed", "https://example.com/fed"),
    ]
    actions = actions_from_rate_points(points, policy_tool="联邦基金目标区间")
    assert [action["type"] for action in actions] == ["加息", "降息", "降息"]
    assert [action["change_bp"] for action in actions] == [50, -25, -25]
    assert actions[0]["date"] == "2026-03-18"
    assert actions[0]["rate_before"] == "3.50-3.75%"
    assert actions[0]["rate_after"] == "4.00-4.25%"


def test_split_default_and_recent_year_keeps_three_default_rows() -> None:
    actions = [
        {"date": "2026-06-17", "type": "加息", "change_bp": 25},
        {"date": "2026-03-19", "type": "维持", "change_bp": 0},
        {"date": "2025-12-22", "type": "加息", "change_bp": 25},
        {"date": "2024-01-23", "type": "加息", "change_bp": 25},
    ]
    split = split_default_and_recent_year(actions, today=date(2026, 6, 26))
    assert [action["date"] for action in split["default_actions"]] == ["2026-06-17", "2026-03-19", "2025-12-22"]
    assert [action["date"] for action in split["recent_year_actions"]] == ["2026-06-17", "2026-03-19", "2025-12-22"]


def test_parse_fed_rows_from_official_snippet() -> None:
    html = (
        "Date Increase Decrease Level (%) "
        "December 11 0 25 3.50-3.75 "
        "October 30 0 25 3.75-4.00 "
        "September 18 0 25 4.00-4.25"
    )
    points = parse_fed_points(html, year=2025)
    assert [point.display_rate for point in points] == ["4.00-4.25%", "3.75-4.00%", "3.50-3.75%"]


def test_parse_fed_rows_skips_ellipsis_change_columns() -> None:
    html = (
        "Date Increase Decrease Level (%) "
        "December 16 ... 75-100 0-0.25 "
        "October 29 ... 50 1.00"
    )
    points = parse_fed_points(html, year=2008)
    assert [(point.date.isoformat(), point.display_rate) for point in points] == [
        ("2008-10-29", "1.00%"),
        ("2008-12-16", "0-0.25%"),
    ]


def test_parse_fed_year_stops_at_the_next_table_heading() -> None:
    html = (
        "2025 Date Increase Decrease Level (%) "
        "December 11 0 25 3.50-3.75 September 18 0 25 4.00-4.25 "
        "2024 Date Increase Decrease Level (%) "
        "December 19 0 25 4.25-4.50 September 19 0 50 4.75-5.00 "
        "2018 Date Increase Decrease Level (%) December 20 25 0 2.25-2.50"
    )
    points = parse_fed_all_points(html, years=[2024, 2025, 2026])
    actions = actions_from_rate_points(points, policy_tool="联邦基金目标区间")
    assert [(point.date.isoformat(), point.display_rate) for point in points] == [
        ("2024-09-19", "4.75-5.00%"),
        ("2024-12-19", "4.25-4.50%"),
        ("2025-09-18", "4.00-4.25%"),
        ("2025-12-11", "3.50-3.75%"),
    ]
    assert all(action["type"] == "降息" for action in actions)
    assert all(action["change_bp"] < 0 for action in actions)


def test_parse_ecb_rows_from_official_snippet() -> None:
    html = "2026 17 Jun. 2.25 2.40 - 2.65 2025 11 Jun. 2.00 2.15 - 2.40 2025 23 Apr. 2.25 2.40 - 2.65"
    points = parse_ecb_points(html)
    assert [(point.date.isoformat(), point.display_rate) for point in points[:3]] == [
        ("2025-04-23", "2.25%"),
        ("2025-06-11", "2.00%"),
        ("2026-06-17", "2.25%"),
    ]


def test_parse_russia_key_rate_rows_from_official_snippet() -> None:
    html = "Date Rate 25.06.2026 14.25 19.06.2026 14.50 18.06.2026 14.50"
    points = parse_russia_points(html)
    assert [(point.date.isoformat(), point.display_rate) for point in points] == [
        ("2026-06-18", "14.50%"),
        ("2026-06-25", "14.25%"),
    ]


def test_parse_korea_base_rate_chart_rows_from_official_page() -> None:
    html = (
        'var chartObj2_s = [["2024/10/11", 3.25],["2024/11/28", 3.00],'
        '["2025/02/25", 2.75],["2025/05/29", 2.50],["2026/06/26", 2.50]];'
    )
    points = parse_korea_base_rate_points(html)
    assert [(point.date.isoformat(), point.display_rate) for point in points[-4:]] == [
        ("2024-11-28", "3.00%"),
        ("2025-02-25", "2.75%"),
        ("2025-05-29", "2.50%"),
        ("2026-06-26", "2.50%"),
    ]
    assert actions_from_rate_points(points, policy_tool="Bank of Korea Base Rate")[0]["date"] == "2025-05-29"


def test_parse_korea_drops_stale_history_before_large_gap() -> None:
    html = 'var chartObj2_s = [["2017/11/30", 1.50],["2026/06/26", 2.50]];'
    points = parse_korea_base_rate_points(html)
    assert [(point.date.isoformat(), point.display_rate) for point in points] == [
        ("2026-06-26", "2.50%"),
    ]
    assert actions_from_rate_points(points, policy_tool="Bank of Korea Base Rate") == []


def test_parse_china_lpr_records_from_chinamoney_json() -> None:
    payload = """
    {"records":[
      {"showDateCN":"2025-05-20","termCode":"1Y","shibor":"3.00"},
      {"showDateCN":"2025-05-20","termCode":"5Y","shibor":"3.50"},
      {"showDateCN":"2025-10-20","termCode":"1Y","shibor":"2.95"},
      {"showDateCN":"2025-10-20","termCode":"5Y","shibor":"3.45"}
    ]}
    """
    points = parse_china_lpr_points(payload)
    assert [(point.date.isoformat(), point.display_rate) for point in points] == [
        ("2025-05-20", "3.00%"),
        ("2025-10-20", "2.95%"),
    ]


def test_parse_china_current_lpr_records_use_data_date() -> None:
    payload = """
    {"data":{"showDateEN":"22/06/2026 9:00","showDateCN":"2026-06-22 9:00"},
     "records":[
       {"termCode":"1Y","shibor":"3.00"},
       {"termCode":"5Y","shibor":"3.50"}
     ]}
    """
    points = parse_china_lpr_points(payload)
    assert [(point.date.isoformat(), point.display_rate) for point in points] == [
        ("2026-06-22", "3.00%"),
    ]


def test_parse_china_lpr_history_rows_from_chinamoney_api() -> None:
    payload = """
    {"data":{"baseCurveCfgList":["1Y","5Y"]},"records":[
      {"5Y":"3.50","1Y":"3.00","showDateEN":"22 Jun 2026","showDateCN":"2026-06-22"},
      {"5Y":"3.50","1Y":"3.00","showDateEN":"20 May 2026","showDateCN":"2026-05-20"},
      {"5Y":"3.60","1Y":"3.10","showDateEN":"20 May 2025","showDateCN":"2025-05-20"}
    ]}
    """
    points = parse_china_lpr_points(payload)
    assert [(point.date.isoformat(), point.display_rate) for point in points] == [
        ("2025-05-20", "3.10%"),
        ("2026-05-20", "3.00%"),
        ("2026-06-22", "3.00%"),
    ]
    actions = actions_from_rate_points(points, policy_tool="1Y Loan Prime Rate")
    assert actions[0]["date"] == "2026-05-20"
    assert actions[0]["type"] == "降息"


def test_fetch_china_lpr_points_chunks_history_requests() -> None:
    requested_urls: list[str] = []

    def fake_fetcher(url: str) -> str:
        requested_urls.append(url)
        return '{"data":{"records":[{"1Y":"3.00","showDateCN":"2026-06-22"}]}}'

    points = fetch_china_lpr_points(fetcher=fake_fetcher, today=date(2026, 6, 26), lookback_days=370)

    assert len(requested_urls) == 2
    assert "strStartDate=21+Jun+2025" in requested_urls[0]
    assert "strEndDate=20+Jun+2026" in requested_urls[0]
    assert "strStartDate=21+Jun+2026" in requested_urls[1]
    assert "strEndDate=26+Jun+2026" in requested_urls[1]
    assert points[0].date.isoformat() == "2026-06-22"


def test_fetch_boj_points_includes_prior_year_for_latest_action_context() -> None:
    index_2024 = '<a href="/en/mopo/mpmdeci/state_2024/k240731a.pdf">Statement on Monetary Policy</a>'
    index_2025 = '<a href="/en/mopo/mpmdeci/state_2025/k250124a.pdf">Statement on Monetary Policy</a>'
    index_2026 = '<a href="/en/mopo/mpmdeci/state_2026/k260123a.pdf">Statement on Monetary Policy</a>'
    pages = {
        policy_rates.BOJ_RELEASE_TEMPLATE.format(year=2024): index_2024,
        policy_rates.BOJ_RELEASE_TEMPLATE.format(year=2025): index_2025,
        policy_rates.BOJ_RELEASE_TEMPLATE.format(year=2026): index_2026,
        "https://www.boj.or.jp/en/mopo/mpmdeci/state_2024/k240731a.pdf": "July 31, 2024 around 0.25 percent",
        "https://www.boj.or.jp/en/mopo/mpmdeci/state_2025/k250124a.pdf": "January 24, 2025 around 0.5 percent",
        "https://www.boj.or.jp/en/mopo/mpmdeci/state_2026/k260123a.pdf": "January 23, 2026 around 0.5 percent",
    }

    points = fetch_boj_points(fetcher=lambda url: pages[url], today=date(2026, 6, 26))
    actions = actions_from_rate_points(points, policy_tool="无担保隔夜拆借利率目标")

    assert [(point.date.isoformat(), point.display_rate) for point in points] == [
        ("2024-07-31", "0.25%"),
        ("2025-01-24", "0.50%"),
        ("2026-01-23", "0.50%"),
    ]
    assert actions[0]["date"] == "2025-01-24"
    assert actions[0]["type"] == "加息"


def test_policy_action_cache_only_changes_when_official_actions_change() -> None:
    first_now = datetime(2026, 6, 26, 12, 0, 0)
    second_now = first_now + timedelta(days=1)
    third_now = first_now + timedelta(days=2)

    def unchanged_fetcher(region: str) -> list[PolicyRatePoint]:
        if region != "US":
            return []
        return [
            PolicyRatePoint("US", date(2025, 12, 11), "3.50-3.75%", 3.75, "Fed", "https://example.com/fed"),
            PolicyRatePoint("US", date(2026, 3, 18), "4.00-4.25%", 4.25, "Fed", "https://example.com/fed"),
        ]

    def changed_fetcher(region: str) -> list[PolicyRatePoint]:
        if region != "US":
            return []
        return [
            PolicyRatePoint("US", date(2025, 12, 11), "3.50-3.75%", 3.75, "Fed", "https://example.com/fed"),
            PolicyRatePoint("US", date(2026, 3, 18), "4.00-4.25%", 4.25, "Fed", "https://example.com/fed"),
            PolicyRatePoint("US", date(2026, 6, 17), "4.25-4.50%", 4.50, "Fed", "https://example.com/fed"),
        ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_path = Path(tmp_dir) / "policy_actions_cache.json"
        first = build_policy_actions(fetcher=unchanged_fetcher, cache_path=cache_path, now=first_now)
        second = build_policy_actions(fetcher=unchanged_fetcher, cache_path=cache_path, now=second_now)
        third = build_policy_actions(fetcher=changed_fetcher, cache_path=cache_path, now=third_now)

    assert first["US"]["action_cache_status"] == "changed"
    assert second["US"]["action_cache_status"] == "unchanged"
    assert second["US"]["action_last_changed_at"] == first["US"]["action_last_changed_at"]
    assert third["US"]["action_cache_status"] == "changed"
    assert third["US"]["action_last_changed_at"] != second["US"]["action_last_changed_at"]


def test_policy_action_fetch_failure_is_scoped_to_one_region() -> None:
    def partial_fetcher(region: str) -> list[PolicyRatePoint]:
        if region == "EU":
            raise RuntimeError("ecb unavailable")
        if region != "US":
            return []
        return [
            PolicyRatePoint("US", date(2025, 12, 11), "3.50-3.75%", 3.75, "Fed", "https://example.com/fed"),
            PolicyRatePoint("US", date(2026, 3, 18), "4.00-4.25%", 4.25, "Fed", "https://example.com/fed"),
        ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_path = Path(tmp_dir) / "policy_actions_cache.json"
        result = build_policy_actions(
            fetcher=partial_fetcher,
            cache_path=cache_path,
            now=datetime(2026, 6, 26, 12, 0, 0),
        )

    assert result["US"]["action_update_source"] == "official"
    assert result["US"]["action_cache_status"] == "changed"
    assert result["US"]["actions"][0]["type"] == "加息"
    assert result["EU"]["action_update_source"] == "fetch_failed"
    assert result["EU"]["actions"] == []


if __name__ == "__main__":
    test_actions_from_rate_points_detects_hikes_and_cuts()
    test_split_default_and_recent_year_keeps_three_default_rows()
    test_parse_fed_rows_from_official_snippet()
    test_parse_fed_rows_skips_ellipsis_change_columns()
    test_parse_ecb_rows_from_official_snippet()
    test_parse_russia_key_rate_rows_from_official_snippet()
    test_parse_korea_base_rate_chart_rows_from_official_page()
    test_parse_korea_drops_stale_history_before_large_gap()
    test_parse_china_lpr_records_from_chinamoney_json()
    test_parse_china_current_lpr_records_use_data_date()
    test_parse_china_lpr_history_rows_from_chinamoney_api()
    test_fetch_china_lpr_points_chunks_history_requests()
    test_fetch_boj_points_includes_prior_year_for_latest_action_context()
    test_policy_action_cache_only_changes_when_official_actions_change()
    test_policy_action_fetch_failure_is_scoped_to_one_region()
    print("policy rate tests passed")
