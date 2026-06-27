#!/usr/bin/env python3
"""Policy-rate news collection and classification for the dashboard."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from policy_rates import build_policy_actions


DEFAULT_MODEL = "gpt-5.4-mini"
ROOT = Path(__file__).resolve().parent
DEFAULT_POLICY_NEWS_CACHE = ROOT / "dashboard" / "data" / "policy_news_cache.json"
DEFAULT_POLICY_NEWS_MAX_AGE_HOURS = 168

POLICY_REGIONS = [
    {
        "code": "US",
        "name": "美国",
        "central_bank": "美联储",
        "query": 'Federal Reserve rate hike OR rate cut OR interest rates',
    },
    {
        "code": "EU",
        "name": "欧元区",
        "central_bank": "欧洲央行",
        "query": 'ECB rate hike OR rate cut OR interest rates',
    },
    {
        "code": "JP",
        "name": "日本",
        "central_bank": "日本央行",
        "query": 'Bank of Japan rate hike OR rate cut OR interest rates',
    },
    {
        "code": "CN",
        "name": "中国",
        "central_bank": "中国央行",
        "query": 'PBOC rate cut OR loan prime rate OR monetary policy',
    },
    {
        "code": "KR",
        "name": "韩国",
        "central_bank": "韩国央行",
        "query": 'Bank of Korea rate hike OR rate cut OR interest rates',
    },
    {
        "code": "RU",
        "name": "俄罗斯",
        "central_bank": "俄罗斯央行",
        "query": 'Bank of Russia rate hike OR rate cut OR key rate',
    },
]

_REGION_BY_CODE = {region["code"]: region for region in POLICY_REGIONS}

POLICY_ACTIONS = {
    "US": {
        "policy_tool": "联邦基金目标区间",
        "source_note": "Federal Reserve Open Market Operations",
        "actions": [
            {
                "date": "2025-12-11",
                "type": "降息",
                "change_bp": -25,
                "rate_before": "3.75-4.00%",
                "rate_after": "3.50-3.75%",
                "source": "Federal Reserve",
                "source_url": "https://www.federalreserve.gov/monetarypolicy/openmarket.htm",
            },
            {
                "date": "2025-10-30",
                "type": "降息",
                "change_bp": -25,
                "rate_before": "4.00-4.25%",
                "rate_after": "3.75-4.00%",
                "source": "Federal Reserve",
                "source_url": "https://www.federalreserve.gov/monetarypolicy/openmarket.htm",
            },
            {
                "date": "2025-09-18",
                "type": "降息",
                "change_bp": -25,
                "rate_before": "4.25-4.50%",
                "rate_after": "4.00-4.25%",
                "source": "Federal Reserve",
                "source_url": "https://www.federalreserve.gov/monetarypolicy/openmarket.htm",
            },
        ],
    },
    "EU": {
        "policy_tool": "ECB deposit facility rate",
        "source_note": "ECB official interest rates",
        "actions": [
            {
                "date": "2026-06-17",
                "type": "加息",
                "change_bp": 25,
                "rate_before": "2.00%",
                "rate_after": "2.25%",
                "source": "ECB",
                "source_url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.en.html",
            },
            {
                "date": "2025-06-11",
                "type": "降息",
                "change_bp": -25,
                "rate_before": "2.25%",
                "rate_after": "2.00%",
                "source": "ECB",
                "source_url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.en.html",
            },
        ],
    },
    "JP": {
        "policy_tool": "无担保隔夜拆借利率目标",
        "source_note": "Bank of Japan Monetary Policy Releases",
        "actions": [
            {
                "date": "2026-06-17",
                "type": "加息",
                "change_bp": 25,
                "rate_before": "0.75%",
                "rate_after": "1.00%",
                "source": "Bank of Japan",
                "source_url": "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k260616a.pdf",
            },
            {
                "date": "2025-12-22",
                "type": "加息",
                "change_bp": 25,
                "rate_before": "0.50%",
                "rate_after": "0.75%",
                "source": "Bank of Japan",
                "source_url": "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2025/k251219a.pdf",
            },
        ],
    },
    "CN": {
        "policy_tool": "1Y Loan Prime Rate",
        "source_note": "NIFC/PBOC Loan Prime Rate",
        "actions": [
            {
                "date": "2025-05-20",
                "type": "降息",
                "change_bp": -10,
                "rate_before": "3.10%",
                "rate_after": "3.00%",
                "source": "NIFC / PBOC LPR",
                "source_url": "https://www.chinamoney.com.cn/english/bmklpr/",
            },
        ],
    },
    "KR": {
        "policy_tool": "Bank of Korea Base Rate",
        "source_note": "Bank of Korea monetary policy decisions",
        "actions": [
            {
                "date": "2025-05-29",
                "type": "降息",
                "change_bp": -25,
                "rate_before": "2.75%",
                "rate_after": "2.50%",
                "source": "Bank of Korea",
                "source_url": "https://www.bok.or.kr/eng/singl/newsDataEng/list.do?menuNo=400022",
            },
        ],
    },
    "RU": {
        "policy_tool": "Bank of Russia Key Rate",
        "source_note": "Bank of Russia key rate decisions",
        "actions": [
            {
                "date": "2026-04-24",
                "type": "降息",
                "change_bp": -50,
                "rate_before": "15.00%",
                "rate_after": "14.50%",
                "source": "Bank of Russia",
                "source_url": "https://www.cbr.ru/eng/hd_base/KeyRate/",
            },
            {
                "date": "2025-12-19",
                "type": "降息",
                "change_bp": -50,
                "rate_before": "16.50%",
                "rate_after": "16.00%",
                "source": "Bank of Russia",
                "source_url": "https://www.cbr.ru/eng/hd_base/KeyRate/",
            },
            {
                "date": "2025-10-24",
                "type": "降息",
                "change_bp": -50,
                "rate_before": "17.00%",
                "rate_after": "16.50%",
                "source": "Bank of Russia",
                "source_url": "https://www.cbr.ru/eng/hd_base/KeyRate/",
            },
            {
                "date": "2025-09-12",
                "type": "降息",
                "change_bp": -100,
                "rate_before": "18.00%",
                "rate_after": "17.00%",
                "source": "Bank of Russia",
                "source_url": "https://www.cbr.ru/eng/hd_base/KeyRate/",
            },
            {
                "date": "2025-07-25",
                "type": "降息",
                "change_bp": -200,
                "rate_before": "20.00%",
                "rate_after": "18.00%",
                "source": "Bank of Russia",
                "source_url": "https://www.cbr.ru/eng/hd_base/KeyRate/",
            },
            {
                "date": "2025-06-06",
                "type": "降息",
                "change_bp": -100,
                "rate_before": "21.00%",
                "rate_after": "20.00%",
                "source": "Bank of Russia",
                "source_url": "https://www.cbr.ru/eng/hd_base/KeyRate/",
            },
        ],
    },
}

FALLBACK_ITEMS = [
    {
        "region": "US",
        "headline": "Federal Reserve officials keep policy-rate guidance data dependent after the latest decision",
        "source": "Federal Reserve",
        "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "published_at": "",
    },
    {
        "region": "EU",
        "headline": "ECB rate-hike speculation returns as inflation risks remain above target",
        "source": "ECB",
        "url": "https://www.ecb.europa.eu/press/pr/date/html/index.en.html",
        "published_at": "",
    },
    {
        "region": "JP",
        "headline": "Bank of Japan discusses gradual rate hikes while monitoring wage and inflation data",
        "source": "Bank of Japan",
        "url": "https://www.boj.or.jp/en/mopo/mpmdeci/index.htm",
        "published_at": "",
    },
    {
        "region": "CN",
        "headline": "PBOC keeps loan prime rates steady while liquidity conditions stay accommodative",
        "source": "PBOC",
        "url": "https://www.pbc.gov.cn/en/3688110/3688172/index.html",
        "published_at": "",
    },
    {
        "region": "KR",
        "headline": "Bank of Korea keeps rates unchanged and says future moves depend on inflation",
        "source": "Bank of Korea",
        "url": "https://www.bok.or.kr/eng/singl/newsDataEng/list.do?menuNo=400022",
        "published_at": "",
    },
    {
        "region": "RU",
        "headline": "Bank of Russia signals tight policy may remain in place if inflation pressure persists",
        "source": "Bank of Russia",
        "url": "https://www.cbr.ru/eng/press/keypr/",
        "published_at": "",
    },
]

HIKE_TERMS = {
    "hike",
    "hikes",
    "hiking",
    "raise",
    "raises",
    "raised",
    "tighten",
    "tightening",
    "hawkish",
    "inflation risk",
    "above target",
    "加息",
    "升息",
    "上调",
    "紧缩",
    "偏鹰",
    "鹰派",
}
CUT_TERMS = {
    "cut",
    "cuts",
    "cutting",
    "lower",
    "lowering",
    "ease",
    "easing",
    "dovish",
    "accommodative",
    "降息",
    "下调",
    "宽松",
    "偏鸽",
    "鸽派",
}
HOLD_TERMS = {
    "hold",
    "holds",
    "keeps",
    "kept",
    "unchanged",
    "steady",
    "pause",
    "data dependent",
    "维持",
    "不变",
    "暂停",
    "观望",
}


def _term_score(text: str, terms: set[str]) -> int:
    return sum(1 for term in terms if term in text)


def classify_policy_news_heuristic(item: dict[str, Any]) -> dict[str, Any]:
    text = f"{item.get('headline', '')} {item.get('summary', '')}".lower()
    hike_score = _term_score(text, HIKE_TERMS)
    cut_score = _term_score(text, CUT_TERMS)
    hold_score = _term_score(text, HOLD_TERMS)
    total = max(1, hike_score + cut_score + hold_score)

    if hike_score > cut_score and hike_score >= hold_score:
        direction = "加息预期升温"
        stance = "偏鹰"
        confidence = min(0.95, 0.55 + 0.1 * hike_score + 0.04 * max(0, hike_score - cut_score))
    elif cut_score > hike_score and cut_score >= hold_score:
        direction = "降息预期升温"
        stance = "偏鸽"
        confidence = min(0.95, 0.55 + 0.1 * cut_score + 0.04 * max(0, cut_score - hike_score))
    elif hold_score:
        direction = "维持观望"
        stance = "中性"
        confidence = min(0.9, 0.5 + 0.1 * hold_score)
    else:
        direction = "不明确"
        stance = "待确认"
        confidence = 0.35

    region = _REGION_BY_CODE.get(str(item.get("region")), {})
    summary = f"{region.get('name', item.get('region', ''))}：{direction}，{stance}。"
    if math.isfinite(total):
        confidence = round(confidence, 2)
    return {
        "region": item.get("region", ""),
        "headline": item.get("headline", ""),
        "source": item.get("source", ""),
        "url": item.get("url", ""),
        "published_at": item.get("published_at", ""),
        "policy_direction": direction,
        "stance": stance,
        "confidence": confidence,
        "summary_cn": summary,
        "analysis": "规则解析",
    }


def _google_news_rss_url(query: str) -> str:
    encoded = quote_plus(f"({query}) when:14d")
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def _text_or_empty(element: ElementTree.Element | None) -> str:
    return unescape((element.text or "").strip()) if element is not None else ""


def fetch_policy_news_items(*, timeout: int = 12, per_region: int = 4) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for region in POLICY_REGIONS:
        request = Request(
            _google_news_rss_url(region["query"]),
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml,text/xml,*/*"},
        )
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
        root = ElementTree.fromstring(payload)
        for item in root.findall("./channel/item")[:per_region]:
            rows.append(
                {
                    "region": region["code"],
                    "headline": _text_or_empty(item.find("title")),
                    "source": "Google News RSS",
                    "url": _text_or_empty(item.find("link")),
                    "published_at": _text_or_empty(item.find("pubDate")),
                }
            )
    return rows


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    for output in payload.get("output", []) or []:
        for content in output.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks)


def analyze_policy_items_with_openai(
    items: list[dict[str, Any]], *, api_key: str, model: str = DEFAULT_MODEL, timeout: int = 45
) -> list[dict[str, Any]]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "region": {"type": "string"},
                        "headline": {"type": "string"},
                        "source": {"type": "string"},
                        "url": {"type": "string"},
                        "published_at": {"type": "string"},
                        "policy_direction": {"type": "string"},
                        "stance": {"type": "string"},
                        "confidence": {"type": "number"},
                        "summary_cn": {"type": "string"},
                        "analysis": {"type": "string"},
                    },
                    "required": [
                        "region",
                        "headline",
                        "source",
                        "url",
                        "published_at",
                        "policy_direction",
                        "stance",
                        "confidence",
                        "summary_cn",
                        "analysis",
                    ],
                },
            }
        },
        "required": ["items"],
    }
    instructions = (
        "你是宏观新闻分类器。只保留与央行加息、降息、维持利率、政策利率预期直接相关的条目。"
        "对每条新闻输出中文 summary_cn，policy_direction 只能表达加息预期升温、降息预期升温、维持观望或不明确，"
        "stance 使用偏鹰、偏鸽、中性或待确认。不要输出任何密钥、环境变量名或多余字段。"
    )
    request_payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": instructions}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps({"items": items}, ensure_ascii=False)}]},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "policy_rate_news",
                "schema": schema,
                "strict": True,
            }
        },
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    text = _extract_response_text(response_payload)
    parsed = json.loads(text)
    result = parsed.get("items", [])
    if not isinstance(result, list):
        raise ValueError("OpenAI policy-news response did not contain an items list")
    return result


def _first_item_per_region(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {region["code"]: [] for region in POLICY_REGIONS}
    for item in items:
        code = str(item.get("region", ""))
        if code in grouped and len(grouped[code]) < 3:
            grouped[code].append(item)
    return grouped


def policy_actions_for_region(code: str) -> dict[str, Any]:
    return POLICY_ACTIONS.get(code, {"policy_tool": "", "source_note": "", "actions": []})


def parse_utc_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_cache_fresh(cache: dict[str, Any], *, now: datetime, max_age_hours: int) -> bool:
    generated_at = parse_utc_timestamp(str(cache.get("generated_at", "")))
    if generated_at is None:
        return False
    return now.astimezone(timezone.utc) - generated_at <= timedelta(hours=max_age_hours)


def load_policy_news_cache(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_policy_news_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_policy_news_snapshot(
    *,
    fetch_news: bool = False,
    use_openai: bool = True,
    model: str | None = None,
    cache_path: Path | None = None,
    max_age_hours: int | None = None,
    force_refresh: bool = False,
    now: datetime | None = None,
    fetcher: Any | None = None,
    analyzer: Any | None = None,
    api_key: str | None = None,
    action_builder: Any | None = None,
) -> dict[str, Any]:
    run_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    model_id = model or os.environ.get("OPENAI_POLICY_NEWS_MODEL", DEFAULT_MODEL)
    cache_file = cache_path or DEFAULT_POLICY_NEWS_CACHE
    cache_max_age = max_age_hours or int(os.environ.get("POLICY_NEWS_MAX_AGE_HOURS", DEFAULT_POLICY_NEWS_MAX_AGE_HOURS))
    news_fetcher = fetcher or fetch_policy_news_items
    news_analyzer = analyzer or analyze_policy_items_with_openai
    selected_api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")

    cached_payload = load_policy_news_cache(cache_file) if fetch_news else None
    analyzed: list[dict[str, Any]]
    news_source = "本地规则样例"
    analysis_source = "规则解析"
    cache_status = "disabled"
    cache_generated_at = ""
    next_update_after = ""

    if fetch_news and cached_payload and not force_refresh and is_cache_fresh(cached_payload, now=run_now, max_age_hours=cache_max_age):
        cached_items = cached_payload.get("items", [])
        analyzed = cached_items if isinstance(cached_items, list) else []
        analysis_source = str(cached_payload.get("analysis_source", "OpenAI"))
        news_source = str(cached_payload.get("news_source", "Google News RSS"))
        cache_status = "fresh"
        cache_generated_at = str(cached_payload.get("generated_at", ""))
    else:
        raw_items: list[dict[str, Any]]
        if fetch_news:
            try:
                raw_items = news_fetcher()
                news_source = "Google News RSS"
            except Exception:
                raw_items = list(FALLBACK_ITEMS)
        else:
            raw_items = list(FALLBACK_ITEMS)

        if fetch_news and use_openai and selected_api_key and raw_items:
            try:
                analyzed = news_analyzer(raw_items, api_key=selected_api_key, model=model_id)
                analysis_source = "OpenAI"
                cache_status = "refreshed"
                generated_at = run_now.isoformat(timespec="seconds")
                cache_payload = {
                    "generated_at": generated_at,
                    "model": model_id,
                    "analysis_source": analysis_source,
                    "news_source": news_source,
                    "items": analyzed,
                }
                write_policy_news_cache(cache_file, cache_payload)
                cache_generated_at = generated_at
                next_update_after = (run_now + timedelta(hours=cache_max_age)).isoformat(timespec="seconds")
            except Exception:
                stale_items = cached_payload.get("items", []) if cached_payload else []
                if stale_items:
                    analyzed = stale_items
                    analysis_source = "stale_cache"
                    cache_status = "stale"
                    cache_generated_at = str(cached_payload.get("generated_at", ""))
                    news_source = str(cached_payload.get("news_source", news_source))
                else:
                    analyzed = [classify_policy_news_heuristic(item) for item in raw_items]
                    cache_status = "fallback"
        else:
            analyzed = [classify_policy_news_heuristic(item) for item in raw_items]
            cache_status = "fallback"

    policy_action_builder = action_builder or build_policy_actions
    try:
        action_rows = policy_action_builder()
    except Exception:
        action_rows = {}

    grouped = _first_item_per_region(analyzed)
    regions: dict[str, dict[str, Any]] = {}
    for region in POLICY_REGIONS:
        items = grouped.get(region["code"]) or [
            classify_policy_news_heuristic(item) for item in FALLBACK_ITEMS if item["region"] == region["code"]
        ]
        action_info = action_rows.get(region["code"]) if isinstance(action_rows, dict) else None
        if not action_info or not action_info.get("actions"):
            action_info = policy_actions_for_region(region["code"])
        default_actions = list(action_info.get("actions", []))[:3]
        recent_year_actions = list(action_info.get("recent_year_actions", action_info.get("actions", [])))
        regions[region["code"]] = {
            "name": region["name"],
            "central_bank": region["central_bank"],
            "items": items[:3],
            "policy_tool": action_info.get("policy_tool", ""),
            "policy_action_source": action_info.get("source_note", ""),
            "actions": default_actions,
            "recent_year_actions": recent_year_actions,
            "action_update_source": action_info.get("action_update_source", "fallback"),
            "action_cache_status": action_info.get("action_cache_status", "fallback"),
            "action_last_changed_at": action_info.get("action_last_changed_at", ""),
            "action_checked_at": action_info.get("action_checked_at", ""),
        }

    return {
        "generated_at": run_now.isoformat(timespec="seconds"),
        "model": model_id,
        "analysis_source": analysis_source,
        "news_source": news_source,
        "cache_status": cache_status,
        "cache_generated_at": cache_generated_at,
        "next_update_after": next_update_after,
        "regions": regions,
        "note": "新闻态度每周自动刷新一次；实际加息/降息操作每天检查官方政策利率记录，有变化才更新。",
    }
