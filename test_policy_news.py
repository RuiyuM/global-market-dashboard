#!/usr/bin/env python3
"""Small checks for the policy-rate news classifier and snapshot shape."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from policy_news import DEFAULT_MODEL, POLICY_REGIONS, build_policy_news_snapshot, classify_policy_news_heuristic


def test_hike_language_is_hawkish() -> None:
    result = classify_policy_news_heuristic(
        {
            "region": "EU",
            "headline": "ECB officials warn another rate hike may be needed as inflation risks rise",
            "source": "sample",
            "url": "",
            "published_at": "2026-06-25",
        }
    )
    assert result["policy_direction"] == "加息预期升温"
    assert result["stance"] == "偏鹰"
    assert result["confidence"] > 0.5


def test_cut_language_is_dovish() -> None:
    result = classify_policy_news_heuristic(
        {
            "region": "CN",
            "headline": "PBOC signals room to lower rates and ease liquidity pressure",
            "source": "sample",
            "url": "",
            "published_at": "2026-06-25",
        }
    )
    assert result["policy_direction"] == "降息预期升温"
    assert result["stance"] == "偏鸽"


def test_snapshot_has_six_regions_and_no_secret_material() -> None:
    snapshot = build_policy_news_snapshot(use_openai=False)
    assert snapshot["model"] == DEFAULT_MODEL
    assert set(snapshot["regions"]) == {region["code"] for region in POLICY_REGIONS}
    assert all(region["items"] for region in snapshot["regions"].values())
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "sk-" not in serialized
    assert "OPENAI_API_KEY" not in serialized


def test_snapshot_includes_recent_policy_actions() -> None:
    def fake_action_builder():
        return {
            region["code"]: {
                "policy_tool": f"{region['name']} policy rate",
                "source_note": "test source",
                "actions": [
                    {
                        "date": "2026-06-17",
                        "type": "加息",
                        "change_bp": 25,
                        "rate_after": "4.25%",
                        "source": "test central bank",
                    },
                    {
                        "date": "2025-12-11",
                        "type": "降息",
                        "change_bp": -25,
                        "rate_after": "4.00%",
                        "source": "test central bank",
                    },
                ],
                "recent_year_actions": [
                    {
                        "date": "2026-06-17",
                        "type": "加息",
                        "change_bp": 25,
                        "rate_after": "4.25%",
                        "source": "test central bank",
                    },
                    {
                        "date": "2025-12-11",
                        "type": "降息",
                        "change_bp": -25,
                        "rate_after": "4.00%",
                        "source": "test central bank",
                    },
                ],
                "action_update_source": "official",
                "action_cache_status": "unchanged",
            }
            for region in POLICY_REGIONS
        }

    snapshot = build_policy_news_snapshot(use_openai=False, action_builder=fake_action_builder)
    for region in snapshot["regions"].values():
        assert region["policy_tool"]
        assert region["actions"]
        for action in region["actions"]:
            assert action["date"]
            assert action["type"] in {"加息", "降息"}
            assert isinstance(action["change_bp"], int)
            assert action["rate_after"]
            assert action["source"]

    us_actions = snapshot["regions"]["US"]["actions"]
    assert [action["date"] for action in us_actions] == ["2026-06-17", "2025-12-11"]
    assert [action["type"] for action in us_actions] == ["加息", "降息"]

    jp_actions = snapshot["regions"]["JP"]["actions"]
    assert any(action["date"] == "2026-06-17" and action["type"] == "加息" for action in jp_actions)


def test_snapshot_uses_automatic_policy_actions() -> None:
    def fake_action_builder():
        return {
            "US": {
                "policy_tool": "联邦基金目标区间",
                "source_note": "test source",
                "actions": [
                    {
                        "date": "2026-03-18",
                        "type": "加息",
                        "change_bp": 50,
                        "rate_after": "4.00-4.25%",
                        "source": "Fed",
                    }
                ],
                "recent_year_actions": [
                    {
                        "date": "2026-03-18",
                        "type": "加息",
                        "change_bp": 50,
                        "rate_after": "4.00-4.25%",
                        "source": "Fed",
                    },
                    {
                        "date": "2025-12-11",
                        "type": "降息",
                        "change_bp": -25,
                        "rate_after": "3.50-3.75%",
                        "source": "Fed",
                    },
                ],
                "action_update_source": "official",
                "action_cache_status": "unchanged",
                "action_last_changed_at": "2026-03-18T00:00:00+00:00",
            }
        }

    snapshot = build_policy_news_snapshot(use_openai=False, action_builder=fake_action_builder)
    us = snapshot["regions"]["US"]
    assert us["actions"][0]["date"] == "2026-03-18"
    assert len(us["recent_year_actions"]) == 2
    assert us["action_update_source"] == "official"
    assert us["action_cache_status"] == "unchanged"


def test_weekly_cache_reuses_fresh_openai_items() -> None:
    now = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_path = Path(tmp_dir) / "policy_news_cache.json"
        snapshot = build_policy_news_snapshot(
            fetch_news=True,
            use_openai=True,
            cache_path=cache_path,
            now=now,
            fetcher=lambda: [
                {
                    "region": "US",
                    "headline": "Fed officials keep rate-cut timing data dependent",
                    "source": "sample",
                    "url": "https://example.com/fed",
                    "published_at": "2026-06-26",
                }
            ],
            analyzer=lambda items, api_key, model: [
                {
                    "region": "US",
                    "headline": items[0]["headline"],
                    "source": items[0]["source"],
                    "url": items[0]["url"],
                    "published_at": items[0]["published_at"],
                    "policy_direction": "维持观望",
                    "stance": "中性",
                    "confidence": 0.82,
                    "summary_cn": "美国：美联储继续强调数据依赖。",
                    "analysis": "OpenAI",
                }
            ],
            api_key="test-key",
        )
        assert snapshot["analysis_source"] == "OpenAI"
        assert snapshot["news_source"] == "Google News RSS"
        assert snapshot["cache_status"] == "refreshed"
        assert cache_path.exists()

        def fail_fetcher():
            raise AssertionError("fresh cache should skip news fetch")

        cached = build_policy_news_snapshot(
            fetch_news=True,
            use_openai=True,
            cache_path=cache_path,
            now=now + timedelta(hours=24),
            fetcher=fail_fetcher,
            analyzer=lambda items, api_key, model: [],
            api_key="test-key",
        )
        assert cached["cache_status"] == "fresh"
        assert cached["regions"]["US"]["items"][0]["summary_cn"] == "美国：美联储继续强调数据依赖。"


def test_weekly_cache_refreshes_after_max_age() -> None:
    now = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_path = Path(tmp_dir) / "policy_news_cache.json"
        build_policy_news_snapshot(
            fetch_news=True,
            use_openai=True,
            cache_path=cache_path,
            now=now,
            fetcher=lambda: [
                {
                    "region": "EU",
                    "headline": "ECB officials discuss inflation risk",
                    "source": "sample",
                    "url": "https://example.com/ecb",
                    "published_at": "2026-06-26",
                }
            ],
            analyzer=lambda items, api_key, model: [
                {
                    "region": "EU",
                    "headline": items[0]["headline"],
                    "source": items[0]["source"],
                    "url": items[0]["url"],
                    "published_at": items[0]["published_at"],
                    "policy_direction": "加息预期升温",
                    "stance": "偏鹰",
                    "confidence": 0.88,
                    "summary_cn": "欧元区：通胀风险让加息讨论升温。",
                    "analysis": "OpenAI",
                }
            ],
            api_key="test-key",
        )

        refreshed = build_policy_news_snapshot(
            fetch_news=True,
            use_openai=True,
            cache_path=cache_path,
            now=now + timedelta(hours=169),
            fetcher=lambda: [
                {
                    "region": "EU",
                    "headline": "ECB signals patience before the next move",
                    "source": "sample",
                    "url": "https://example.com/ecb-new",
                    "published_at": "2026-07-03",
                }
            ],
            analyzer=lambda items, api_key, model: [
                {
                    "region": "EU",
                    "headline": items[0]["headline"],
                    "source": items[0]["source"],
                    "url": items[0]["url"],
                    "published_at": items[0]["published_at"],
                    "policy_direction": "维持观望",
                    "stance": "中性",
                    "confidence": 0.8,
                    "summary_cn": "欧元区：欧洲央行更偏向等待。",
                    "analysis": "OpenAI",
                }
            ],
            api_key="test-key",
        )
        assert refreshed["cache_status"] == "refreshed"
        assert refreshed["regions"]["EU"]["items"][0]["summary_cn"] == "欧元区：欧洲央行更偏向等待。"


if __name__ == "__main__":
    test_hike_language_is_hawkish()
    test_cut_language_is_dovish()
    test_snapshot_has_six_regions_and_no_secret_material()
    test_snapshot_includes_recent_policy_actions()
    test_snapshot_uses_automatic_policy_actions()
    test_weekly_cache_reuses_fresh_openai_items()
    test_weekly_cache_refreshes_after_max_age()
    print("policy news tests passed")
