#!/usr/bin/env python3
"""Fetch official policy-rate histories and convert them to hike/cut actions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_POLICY_ACTIONS_CACHE = ROOT / "dashboard" / "data" / "policy_actions_cache.json"


@dataclass(frozen=True)
class PolicyRatePoint:
    region: str
    date: date
    display_rate: str
    numeric_rate: float
    source: str
    source_url: str


POLICY_RATE_SOURCES = {
    "US": {"policy_tool": "联邦基金目标区间", "source_note": "Federal Reserve FOMC target range"},
    "EU": {"policy_tool": "ECB deposit facility rate", "source_note": "ECB key interest rates"},
    "JP": {"policy_tool": "无担保隔夜拆借利率目标", "source_note": "Bank of Japan monetary policy releases"},
    "CN": {"policy_tool": "1Y Loan Prime Rate", "source_note": "NIFC/PBOC Loan Prime Rate"},
    "KR": {"policy_tool": "Bank of Korea Base Rate", "source_note": "Bank of Korea monetary policy decisions"},
    "RU": {"policy_tool": "Bank of Russia Key Rate", "source_note": "Bank of Russia key rate"},
}

FED_URL = "https://www.federalreserve.gov/monetarypolicy/openmarket.htm"
ECB_URL = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.en.html"
BOJ_RELEASE_BASE = "https://www.boj.or.jp/en/mopo/mpmdeci/"
BOJ_RELEASE_TEMPLATE = "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_{year}/index.htm"
CHINA_LPR_URL = "https://www.chinamoney.com.cn/english/bmklpr/"
CHINA_LPR_CURRENT_URL = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/currency/bk-lpr.json"
CHINA_LPR_HISTORY_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis"
BOK_URL = "https://www.bok.or.kr/eng/singl/baseRate/progress.do?dataSeCd=01&menuNo=400016"
RUSSIA_URL = "https://www.cbr.ru/eng/hd_base/KeyRate/?UniDbQuery.Posted=True"

MONTHS = {
    "Jan": 1,
    "January": 1,
    "Feb": 2,
    "February": 2,
    "Mar": 3,
    "March": 3,
    "Apr": 4,
    "April": 4,
    "May": 5,
    "Jun": 6,
    "June": 6,
    "Jul": 7,
    "July": 7,
    "Aug": 8,
    "August": 8,
    "Sep": 9,
    "Sept": 9,
    "September": 9,
    "Oct": 10,
    "October": 10,
    "Nov": 11,
    "November": 11,
    "Dec": 12,
    "December": 12,
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u2212", "-").replace("\xa0", " ")).strip()


def format_percent(value: float | str) -> str:
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "")
        return f"{cleaned}%"
    return f"{value:.2f}%"


def numeric_rate_from_display(value: str) -> float:
    cleaned = value.replace("%", "").strip()
    if "-" in cleaned:
        return float(cleaned.split("-")[-1])
    return float(cleaned)


def fetch_text(url: str, *, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,text/plain,*/*"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
        encoding = response.headers.get_content_charset() or "utf-8"
    return data.decode(encoding, errors="replace")


def actions_from_rate_points(points: list[PolicyRatePoint], *, policy_tool: str) -> list[dict[str, Any]]:
    ordered = sorted(points, key=lambda row: row.date)
    actions: list[dict[str, Any]] = []
    for previous, current in zip(ordered, ordered[1:]):
        change_bp = int(round((current.numeric_rate - previous.numeric_rate) * 100))
        if change_bp == 0:
            continue
        action_type = "加息" if change_bp > 0 else "降息"
        actions.append(
            {
                "date": current.date.isoformat(),
                "type": action_type,
                "change_bp": change_bp,
                "rate_before": previous.display_rate,
                "rate_after": current.display_rate,
                "source": current.source,
                "source_url": current.source_url,
                "policy_tool": policy_tool,
            }
        )
    return list(reversed(actions))


def split_default_and_recent_year(actions: list[dict[str, Any]], *, today: date | None = None) -> dict[str, list[dict[str, Any]]]:
    run_date = today or datetime.now(timezone.utc).date()
    cutoff = run_date - timedelta(days=365)
    default_actions = actions[:3]
    recent_year_actions = [action for action in actions if date.fromisoformat(action["date"]) >= cutoff]
    return {"default_actions": default_actions, "recent_year_actions": recent_year_actions}


def action_signature(rows: dict[str, dict[str, Any]]) -> str:
    serializable = {
        code: [
            {
                "date": action.get("date", ""),
                "type": action.get("type", ""),
                "change_bp": action.get("change_bp", 0),
                "rate_after": action.get("rate_after", ""),
            }
            for action in payload.get("recent_year_actions", [])
        ]
        for code, payload in sorted(rows.items())
    }
    return json.dumps(serializable, ensure_ascii=False, sort_keys=True)


def parse_fed_points(html: str, *, year: int) -> list[PolicyRatePoint]:
    text = normalize_text(re.sub(r"<[^>]+>", " ", html))
    rows: list[PolicyRatePoint] = []
    change_token = r"(?:\.\.\.|\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)"
    pattern = re.compile(
        r"\b("
        + "|".join(sorted(MONTHS, key=len, reverse=True))
        + rf")\.?\s+(\d{{1,2}})(?:\*|\[[^\]]+\])?\s+({change_token})\s+({change_token})\s+(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)"
    )
    for month_name, day_text, increase, decrease, level in pattern.findall(text):
        if increase in {"0", "0.0", "0.00"} and decrease in {"0", "0.0", "0.00"}:
            continue
        month = MONTHS[month_name.rstrip(".")]
        rate_date = date(year, month, int(day_text))
        display = format_percent(level)
        rows.append(PolicyRatePoint("US", rate_date, display, numeric_rate_from_display(display), "Federal Reserve", FED_URL))
    return sorted({(row.date, row.display_rate): row for row in rows}.values(), key=lambda row: row.date)


def parse_fed_all_points(html: str, *, years: list[int]) -> list[PolicyRatePoint]:
    text = normalize_text(re.sub(r"<[^>]+>", " ", html))
    rows: list[PolicyRatePoint] = []
    for year in years:
        start = text.find(f"{year} Date Increase Decrease Level")
        if start == -1:
            start = text.find(f"{year} ")
        if start == -1:
            continue
        next_year_positions = [pos for candidate in years if candidate != year and (pos := text.find(f"{candidate} ", start + 4)) != -1]
        end = min(next_year_positions) if next_year_positions else len(text)
        rows.extend(parse_fed_points(text[start:end], year=year))
    return sorted({(row.date, row.display_rate): row for row in rows}.values(), key=lambda row: row.date)


def parse_ecb_points(html: str) -> list[PolicyRatePoint]:
    text = normalize_text(re.sub(r"<[^>]+>", " ", html))
    pattern = re.compile(r"\b(20\d{2})\s+(\d{1,2})\s+([A-Z][a-z]+)\.?\s+(-?\d+(?:\.\d+)?)\s+[-\d.]+\s+(?:-|[-\d.]+)\s+[-\d.]+")
    rows: list[PolicyRatePoint] = []
    for year_text, day_text, month_name, deposit_rate in pattern.findall(text):
        month = MONTHS.get(month_name.rstrip("."))
        if not month:
            continue
        rate_date = date(int(year_text), month, int(day_text))
        display = format_percent(deposit_rate)
        rows.append(PolicyRatePoint("EU", rate_date, display, float(deposit_rate), "ECB", ECB_URL))
    return sorted({(row.date, row.display_rate): row for row in rows}.values(), key=lambda row: row.date)


def parse_russia_points(html: str) -> list[PolicyRatePoint]:
    text = normalize_text(re.sub(r"<[^>]+>", " ", html))
    pattern = re.compile(r"\b(\d{2})\.(\d{2})\.(20\d{2})\s+(\d+(?:\.\d+)?)")
    daily_rows: list[PolicyRatePoint] = []
    for day_text, month_text, year_text, rate_text in pattern.findall(text):
        rate_date = date(int(year_text), int(month_text), int(day_text))
        display = format_percent(rate_text)
        daily_rows.append(PolicyRatePoint("RU", rate_date, display, float(rate_text), "Bank of Russia", RUSSIA_URL))

    compressed: list[PolicyRatePoint] = []
    for row in sorted(daily_rows, key=lambda item: item.date):
        if not compressed or row.numeric_rate != compressed[-1].numeric_rate:
            compressed.append(row)
    return compressed


def parse_china_lpr_points(html: str) -> list[PolicyRatePoint]:
    def parse_lpr_date(raw_date: str) -> date | None:
        numeric_match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", raw_date)
        if numeric_match:
            year_text, month_text, day_text = numeric_match.groups()
            return date(int(year_text), int(month_text), int(day_text))
        month_match = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(20\d{2})\b", raw_date)
        if month_match:
            day_text, month_name, year_text = month_match.groups()
            month = MONTHS.get(month_name.rstrip("."))
            if month:
                return date(int(year_text), month, int(day_text))
        return None

    json_rows: list[PolicyRatePoint] = []
    try:
        parsed = json.loads(html)
    except json.JSONDecodeError:
        parsed = None
    records: list[Any] = []
    common_date = ""
    if isinstance(parsed, dict):
        containers: list[Any] = [parsed]
        if isinstance(parsed.get("data"), dict):
            containers.append(parsed["data"])
            common_date = str(parsed["data"].get("showDateCN") or parsed["data"].get("showDateEN") or "")
        if isinstance(parsed.get("result"), dict):
            containers.append(parsed["result"])
        for container in containers:
            if isinstance(container, dict) and isinstance(container.get("records"), list):
                records.extend(container["records"])
    elif isinstance(parsed, list):
        records = parsed

    if records:
        for record in records:
            if not isinstance(record, dict):
                continue
            if "1Y" in record:
                raw_rate = str(record.get("1Y") or "")
            else:
                term = str(record.get("termCode") or record.get("term") or record.get("prdTerm") or "")
                if term and term.upper() not in {"1Y", "1年", "LPR1Y"}:
                    continue
                raw_rate = str(record.get("shibor") or record.get("rate") or record.get("value") or "")
            raw_date = str(
                record.get("showDateCN")
                or record.get("showDateEN")
                or record.get("date")
                or record.get("showDate")
                or common_date
                or ""
            )
            rate_date = parse_lpr_date(raw_date)
            rate_match = re.search(r"-?\d+(?:\.\d+)?", raw_rate)
            if not rate_date or not rate_match:
                continue
            rate = float(rate_match.group(0))
            display = format_percent(rate)
            json_rows.append(PolicyRatePoint("CN", rate_date, display, rate, "NIFC / PBOC LPR", CHINA_LPR_URL))
        if json_rows:
            return sorted({(row.date, row.display_rate): row for row in json_rows}.values(), key=lambda row: row.date)

    record_pattern = re.compile(
        r'"(?:showDateCN|showDateEN|date|showDate)"\s*:\s*"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})".{0,240}?'
        r'"(?:termCode|term|prdTerm)"\s*:\s*"(?:1Y|1年|LPR1Y)".{0,240}?'
        r'"(?:shibor|rate|value)"\s*:\s*"?(?P<rate>\d+(?:\.\d+)?)',
        flags=re.DOTALL,
    )
    for match in record_pattern.finditer(html):
        year_text, month_text, day_text = re.split(r"[-/.]", match.group(1))
        rate = float(match.group("rate"))
        display = format_percent(rate)
        json_rows.append(
            PolicyRatePoint(
                "CN",
                date(int(year_text), int(month_text), int(day_text)),
                display,
                rate,
                "NIFC / PBOC LPR",
                CHINA_LPR_URL,
            )
        )
    if json_rows:
        return sorted({(row.date, row.display_rate): row for row in json_rows}.values(), key=lambda row: row.date)

    text = normalize_text(re.sub(r"<[^>]+>", " ", html))
    patterns = [
        re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"),
        re.compile(r"\b(20\d{2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"),
    ]
    rows: list[PolicyRatePoint] = []
    for pattern in patterns:
        for year_text, month_text, day_text, one_year, _five_year in pattern.findall(text):
            rate_date = date(int(year_text), int(month_text), int(day_text))
            display = format_percent(one_year)
            rows.append(PolicyRatePoint("CN", rate_date, display, float(one_year), "NIFC / PBOC LPR", CHINA_LPR_URL))
        if rows:
            break
    return sorted({(row.date, row.display_rate): row for row in rows}.values(), key=lambda row: row.date)


def format_chinamoney_lpr_date(value: date) -> str:
    month_abbr = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{value.day:02d} {month_abbr[value.month - 1]} {value.year}"


def fetch_china_lpr_points(
    *,
    fetcher: Callable[[str], str] = fetch_text,
    today: date | None = None,
    lookback_days: int = 1095,
) -> list[PolicyRatePoint]:
    run_date = today or datetime.now(timezone.utc).date()
    start_date = run_date - timedelta(days=lookback_days)
    rows: list[PolicyRatePoint] = []
    chunk_start = start_date
    while chunk_start <= run_date:
        chunk_end = min(chunk_start + timedelta(days=364), run_date)
        params = urlencode(
            {
                "lang": "EN",
                "strStartDate": format_chinamoney_lpr_date(chunk_start),
                "strEndDate": format_chinamoney_lpr_date(chunk_end),
            }
        )
        try:
            rows.extend(parse_china_lpr_points(fetcher(f"{CHINA_LPR_HISTORY_URL}?{params}")))
        except Exception:
            pass
        chunk_start = chunk_end + timedelta(days=1)

    if not rows:
        rows.extend(parse_china_lpr_points(fetcher(CHINA_LPR_CURRENT_URL)))
    return sorted({(row.date, row.display_rate): row for row in rows}.values(), key=lambda row: row.date)


def parse_korea_base_rate_points(html: str) -> list[PolicyRatePoint]:
    def trim_large_history_gap(points: list[PolicyRatePoint]) -> list[PolicyRatePoint]:
        ordered = sorted(points, key=lambda row: row.date)
        for index in range(1, len(ordered)):
            if (ordered[index].date - ordered[index - 1].date).days > 548:
                ordered = ordered[index:]
                break
        return ordered

    rows: list[PolicyRatePoint] = []
    chart_match = re.search(r"chartObj2_s\s*=\s*(\[[\s\S]*?\])\s*;", html)
    if chart_match:
        for year_text, month_text, day_text, rate_text in re.findall(
            r'\[\s*"(\d{4})/(\d{1,2})/(\d{1,2})"\s*,\s*(-?\d+(?:\.\d+)?)\s*\]',
            chart_match.group(1),
        ):
            rate_date = date(int(year_text), int(month_text), int(day_text))
            display = format_percent(rate_text)
            rows.append(PolicyRatePoint("KR", rate_date, display, float(rate_text), "Bank of Korea", BOK_URL))
        if rows:
            deduped = sorted({(row.date, row.display_rate): row for row in rows}.values(), key=lambda row: row.date)
            return trim_large_history_gap(deduped)

    text = normalize_text(re.sub(r"<[^>]+>", " ", html))
    pattern = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2}).{0,120}?(?:Base Rate|base rate|기준금리).{0,80}?(\d+(?:\.\d+)?)\s*%")
    for year_text, month_text, day_text, rate_text in pattern.findall(text):
        rate_date = date(int(year_text), int(month_text), int(day_text))
        display = format_percent(rate_text)
        rows.append(PolicyRatePoint("KR", rate_date, display, float(rate_text), "Bank of Korea", BOK_URL))
    deduped = sorted({(row.date, row.display_rate): row for row in rows}.values(), key=lambda row: row.date)
    return trim_large_history_gap(deduped)


def parse_boj_statement_points(text: str, *, source_url: str) -> list[PolicyRatePoint]:
    normalized = normalize_text(re.sub(r"<[^>]+>", " ", text))
    date_match = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", normalized)
    if not date_match:
        month_match = re.search(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2}),\s+(20\d{2})", normalized)
        if not month_match:
            return []
        month_name, day_text, year_text = month_match.groups()
        rate_date = date(int(year_text), MONTHS[month_name.rstrip(".")], int(day_text))
    else:
        year_text, month_text, day_text = date_match.groups()
        rate_date = date(int(year_text), int(month_text), int(day_text))

    rate_match = re.search(r"(?:around|at)\s+(-?\d+(?:\.\d+)?)\s*percent", normalized, flags=re.IGNORECASE)
    if not rate_match:
        return []
    rate = float(rate_match.group(1))
    display = format_percent(rate)
    return [PolicyRatePoint("JP", rate_date, display, rate, "Bank of Japan", source_url)]


def fetch_boj_points(
    *,
    fetcher: Callable[[str], str] = fetch_text,
    today: date | None = None,
) -> list[PolicyRatePoint]:
    rows: list[PolicyRatePoint] = []
    current_year = (today or datetime.now(timezone.utc).date()).year
    for year in range(current_year - 2, current_year + 1):
        index_url = BOJ_RELEASE_TEMPLATE.format(year=year)
        try:
            index_html = fetcher(index_url)
        except Exception:
            continue
        links = re.findall(r'href="([^"]+)">(?:[^<]*Statement on Monetary Policy|[^<]*Change in the Guideline for Money Market Operations)', index_html)
        for href in links[:8]:
            source_url = urljoin(index_url, href)
            try:
                text = fetcher(source_url)
            except Exception:
                continue
            rows.extend(parse_boj_statement_points(text, source_url=source_url))
    return sorted({(row.date, row.display_rate): row for row in rows}.values(), key=lambda row: row.date)


def fetch_policy_rate_points(region: str) -> list[PolicyRatePoint]:
    current_year = datetime.now(timezone.utc).year
    if region == "US":
        html = fetch_text(FED_URL)
        return parse_fed_all_points(html, years=[current_year - 2, current_year - 1, current_year])
    if region == "EU":
        return parse_ecb_points(fetch_text(ECB_URL))
    if region == "RU":
        return parse_russia_points(fetch_text(RUSSIA_URL))
    if region == "CN":
        return fetch_china_lpr_points()
    if region == "KR":
        return parse_korea_base_rate_points(fetch_text(BOK_URL))
    if region == "JP":
        return fetch_boj_points()
    return []


def build_policy_actions_from_official_sources(
    fetcher: Callable[[str], list[PolicyRatePoint]] = fetch_policy_rate_points,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for region, meta in POLICY_RATE_SOURCES.items():
        try:
            points = fetcher(region)
            actions = actions_from_rate_points(points, policy_tool=meta["policy_tool"])
        except Exception as exc:
            result[region] = {
                "policy_tool": meta["policy_tool"],
                "source_note": meta["source_note"],
                "actions": [],
                "recent_year_actions": [],
                "action_update_source": "fetch_failed",
                "action_cache_status": "candidate",
                "action_error": str(exc)[:180],
            }
            continue

        split = split_default_and_recent_year(actions)
        result[region] = {
            "policy_tool": meta["policy_tool"],
            "source_note": meta["source_note"],
            "actions": split["default_actions"],
            "recent_year_actions": split["recent_year_actions"],
            "action_update_source": "official",
            "action_cache_status": "candidate",
        }
    return result


def load_policy_actions_cache(path: Path | str) -> dict[str, Any] | None:
    cache_path = Path(path)
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_policy_actions_cache(path: Path | str, payload: dict[str, Any]) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_policy_actions(
    fetcher: Callable[[str], list[PolicyRatePoint]] = fetch_policy_rate_points,
    *,
    cache_path: Path | str = DEFAULT_POLICY_ACTIONS_CACHE,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    run_now = now or datetime.now(timezone.utc)
    checked_at = run_now.isoformat(timespec="seconds")
    cached = load_policy_actions_cache(cache_path)
    try:
        fresh = build_policy_actions_from_official_sources(fetcher)
    except Exception:
        if cached and isinstance(cached.get("regions"), dict):
            cached_regions = cached["regions"]
            for region in cached_regions.values():
                region["action_cache_status"] = "cache_fallback"
                region["action_last_changed_at"] = cached.get("last_changed_at", "")
                region["action_checked_at"] = checked_at
            return cached_regions
        return {}

    cached_regions = cached.get("regions", {}) if cached and isinstance(cached.get("regions"), dict) else {}
    for code, region in list(fresh.items()):
        if region.get("action_update_source") != "fetch_failed":
            continue
        cached_region = cached_regions.get(code)
        if isinstance(cached_region, dict) and cached_region.get("actions"):
            replacement = dict(cached_region)
            replacement["action_update_source"] = "cache"
            replacement["action_cache_status"] = "cache_fallback"
            replacement["action_last_changed_at"] = cached.get("last_changed_at", "")
            replacement["action_checked_at"] = checked_at
            fresh[code] = replacement

    fresh_signature = action_signature(fresh)
    cached_signature = str(cached.get("signature", "")) if cached else ""
    if fresh_signature != cached_signature:
        payload = {
            "checked_at": checked_at,
            "last_changed_at": checked_at,
            "signature": fresh_signature,
            "regions": fresh,
        }
        write_policy_actions_cache(cache_path, payload)
        for region in fresh.values():
            if region.get("action_cache_status") != "cache_fallback":
                region["action_cache_status"] = "changed"
            region["action_last_changed_at"] = payload["last_changed_at"]
            region["action_checked_at"] = checked_at
        return fresh

    regions = cached["regions"] if cached and isinstance(cached.get("regions"), dict) else fresh
    for region in regions.values():
        if region.get("action_cache_status") != "cache_fallback":
            region["action_cache_status"] = "unchanged"
        region["action_last_changed_at"] = cached.get("last_changed_at", "") if cached else checked_at
        region["action_checked_at"] = checked_at
    return regions
