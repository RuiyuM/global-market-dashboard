"""Official weekly Japanese cross-border securities flows for the route tracker."""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


MOF_SOURCE = "日本财务省"
MOF_CSV_URL = "https://www.mof.go.jp/policy/international_policy/reference/itn_transactions_in_securities/week.csv"
MOF_SOURCE_URL = "https://www.mof.go.jp/english/policy/international_policy/reference/itn_transactions_in_securities/index.htm"
MOF_SCHEDULE_URL = "https://www.mof.go.jp/english/policy/international_policy/reference/itn_transactions_in_securities/schedule.htm"
MOF_TZ = ZoneInfo("Asia/Tokyo")
MOF_RELEASE_TIME = time(8, 50, tzinfo=MOF_TZ)
MAX_DOWNLOAD_BYTES = 2_000_000
FLOW_FIELDS = ("short_net", "long_net", "equity_net")
MONTHS = {
    name: number
    for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December"),
        start=1,
    )
}
WEEK_RANGE = re.compile(
    r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*~\s*"
    r"(?:(\d{4})\s*\.\s*)?(\d{1,2})\s*\.\s*(\d{1,2})"
)


def _date_en(text: str) -> date:
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2})\s*,\s*(\d{4})", text.strip())
    if not match or match[1] not in MONTHS:
        raise ValueError("invalid English MOF date")
    return date(int(match[3]), MONTHS[match[1]], int(match[2]))


def _valid_week_end(day: date) -> bool:
    return day.weekday() == 5


def _number(text: str) -> int:
    normalized = unicodedata.normalize("NFKC", text).strip().replace("−", "-")
    if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)", normalized):
        raise ValueError("invalid MOF flow number")
    return int(normalized.replace(",", ""))


def decode_mof(body: bytes) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("cp932")


def parse_mof_csv(text: str) -> tuple[str, dict[str, dict[str, int]]]:
    rows = list(csv.reader(io.StringIO(text), strict=True))
    if len(rows) < 15:
        raise ValueError("missing MOF weekly CSV headers")
    if (
        not rows[1] or not rows[1][0].startswith("International Transactions in Securities (Weekly;")
        or len(rows[4]) <= 19 or rows[4][19].strip() != "Unit: 100 million Yen"
        or len(rows[8]) <= 12 or rows[8][12].strip() != "2. Portfolio Investment Liabilities"
        or len(rows[11]) <= 19
        or tuple(rows[11][column].strip() for column in (12, 15, 19))
          != ("Equity and investment fund shares", "Long-term debt securities", "Short-term debt securities")
        or len(rows[13]) <= 22
        or any(rows[13][column].strip() != "Net" for column in (14, 17, 21, 22))
    ):
        raise ValueError("unexpected MOF weekly CSV schema or units")

    updated_cell = rows[1][19] if len(rows[1]) > 19 else ""
    if not updated_cell.startswith("Final Update"):
        raise ValueError("missing MOF weekly CSV update date")
    updated = _date_en(updated_cell.removeprefix("Final Update"))
    weeks = {}
    last = None
    for row in rows[14:]:
        period = unicodedata.normalize("NFKC", row[0]).strip() if row else ""
        if not period:
            break
        match = WEEK_RANGE.fullmatch(period)
        if not match or len(row) < 23:
            raise ValueError("unexpected MOF weekly CSV row")
        year, month, day, end_year, end_month, end_day = match.groups()
        week_start = date(int(year), int(month), int(day))
        week_end = date(int(end_year or year), int(end_month), int(end_day))
        if (
            not _valid_week_end(week_end) or (week_end - week_start).days != 6
            or week_end > updated or (last is not None and week_end <= last)
        ):
            raise ValueError("invalid or out-of-order MOF reference week")
        flows = {}
        for field, column in zip(("equity_net", "long_net", "short_net"), (12, 15, 19)):
            acquisition, disposition, net = (_number(value) for value in row[column:column + 3])
            if acquisition < 0 or disposition < 0 or abs(acquisition - disposition - net) > 1:
                raise ValueError("MOF published net inconsistent with underlying totals")
            flows[field] = net
        if abs(_number(row[22]) - sum(flows.values())) > 2:
            raise ValueError("MOF published aggregate inconsistent with category totals")
        weeks[week_end.isoformat()] = flows
        last = week_end
    if not weeks:
        raise ValueError("empty MOF weekly CSV")
    return updated.isoformat(), weeks


class _ScheduleTable(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_mof_schedule(text: str) -> dict[str, str]:
    table = _ScheduleTable()
    table.feed(text)
    table.close()
    plan: dict[str, str] = {}
    week_range = re.compile(
        r"([A-Za-z]+)\s+(\d{1,2})(?:\s*,\s*(\d{4}))?\s*[-–—]\s*"
        r"(?:([A-Za-z]+)\s+)?(\d{1,2})\s*,\s*(\d{4})"
    )
    for cells in table.rows:
        if len(cells) != 2:
            continue
        try:
            release = _date_en(cells[0])
        except ValueError:
            continue
        for subject in cells[1].split("/"):
            match = week_range.fullmatch(subject.strip())
            if not match:
                continue  # Monthly releases are irrelevant to the weekly tracker.
            start_month, start_day, start_year, end_month, end_day, end_year = match.groups()
            if start_month not in MONTHS or (end_month or start_month) not in MONTHS:
                raise ValueError("invalid MOF release month")
            start_month_number = MONTHS[start_month]
            end_month_number = MONTHS[end_month or start_month]
            end_year_number = int(end_year)
            start_year_number = int(start_year) if start_year else end_year_number - (start_month_number > end_month_number)
            start = date(start_year_number, start_month_number, int(start_day))
            end = date(end_year_number, end_month_number, int(end_day))
            if not _valid_week_end(end) or (end - start).days != 6 or release <= end:
                raise ValueError("invalid scheduled MOF reference week or publication date")
            end_key = end.isoformat()
            if end_key in plan and plan[end_key] != release.isoformat():
                raise ValueError("conflicting MOF publication dates")
            plan[end_key] = release.isoformat()
    if not plan:
        raise ValueError("empty MOF weekly release schedule")
    return plan


def _download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "global-market-dashboard/1.0"})
    with urlopen(request, timeout=8) as response:
        body = response.read(MAX_DOWNLOAD_BYTES + 1)
    if not body or len(body) > MAX_DOWNLOAD_BYTES:
        raise ValueError("invalid MOF response size")
    return body


def _date_key(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("expected an ISO date")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("expected a canonical ISO date")
    return parsed


def _read_cache(path: Path, today: date) -> dict[str, Any]:
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict) or cache.get("version") != 1:
            return {}
        weeks = cache["weeks"]
        schedule = cache["schedule"]
        updated_at = cache["updated_at"]
        if not isinstance(weeks, dict) or not isinstance(schedule, dict):
            return {}
        if weeks:
            updated = _date_key(updated_at)
            if updated > today:
                return {}
            for key, data in weeks.items():
                end = _date_key(key)
                if not _valid_week_end(end) or end > updated:
                    return {}
                if not isinstance(data, dict) or any(type(data.get(field)) is not int for field in FLOW_FIELDS):
                    return {}
        elif updated_at is not None:
            return {}
        for key, value in schedule.items():
            end = _date_key(key)
            if not _valid_week_end(end) or _date_key(value) <= end:
                return {}
        return {"version": 1, "weeks": weeks, "schedule": schedule, "updated_at": updated_at}
    except (OSError, KeyError, ValueError):
        return {}


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            scratch = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        scratch.replace(path)
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)


def _fetch_record(key: str, url: str, rows: dict, path: Path, error: str = "") -> dict[str, str]:
    return {
        "key": key,
        "source": "japan-mof",
        "symbol": url,
        "status": ("degraded" if rows else "error") if error else "ok",
        "rows": str(len(rows)),
        "latest": max(rows, default=""),
        "file": str(path),
        "error": error,
    }


def _tokyo_now(now: datetime) -> datetime:
    if now.utcoffset() is None:
        raise ValueError("MOF as-of time must include a time zone")
    return now.astimezone(MOF_TZ)


def load_route_market_flows(cache_path: Path, *, refresh: bool, now: datetime) -> dict[str, Any]:
    tokyo_now = _tokyo_now(now)
    data = _read_cache(cache_path, tokyo_now.date()) or {
        "version": 1, "weeks": {}, "schedule": {}, "updated_at": None,
    }
    if not refresh:
        return {**data, "fetch_records": []}

    original = data.copy()
    csv_error = schedule_error = ""
    try:
        updated_at, weeks = parse_mof_csv(decode_mof(_download(MOF_CSV_URL)))
        if _date_key(updated_at) > tokyo_now.date():
            raise ValueError("MOF weekly CSV update date is in the future")
        if data["weeks"] and (
            updated_at < data["updated_at"] or not data["weeks"].keys() <= weeks.keys()
        ):
            raise ValueError("MOF weekly CSV is older or missing previously reported weeks")
        data.update(weeks=weeks, updated_at=updated_at)
    except (OSError, ValueError, csv.Error) as exc:
        csv_error = str(exc) or type(exc).__name__

    try:
        schedule = parse_mof_schedule(decode_mof(_download(MOF_SCHEDULE_URL)))
        if data["schedule"] and max(schedule) < max(data["schedule"]):
            raise ValueError("MOF release schedule ends before the retained schedule")
        data["schedule"] = data["schedule"] | schedule
    except (OSError, ValueError) as exc:
        schedule_error = str(exc) or type(exc).__name__

    due = [
        week for week, release in data["schedule"].items()
        if datetime.combine(_date_key(release), MOF_RELEASE_TIME) <= tokyo_now
    ]
    if not csv_error and due and max(due) not in data["weeks"]:
        csv_error = f"MOF weekly CSV missing scheduled week ending {max(due)}"

    if data != original:
        try:
            _write_cache(cache_path, data)
        except OSError as exc:
            message = f"MOF cache write failed: {exc}"
            csv_error = f"{csv_error}; {message}" if csv_error else message
            schedule_error = f"{schedule_error}; {message}" if schedule_error else message
            data = original
    return {
        **data,
        "fetch_records": [
            _fetch_record("JP_MOF_PORTFOLIO_WEEKLY", MOF_CSV_URL, data["weeks"], cache_path, csv_error),
            _fetch_record("JP_MOF_PORTFOLIO_RELEASE_SCHEDULE", MOF_SCHEDULE_URL, data["schedule"], cache_path, schedule_error),
        ],
    }


def _flow_for_route(destination: str, signal_date: date, data: dict[str, Any], now: datetime) -> dict[str, Any]:
    flow = {
        "status": "unavailable", "source": None, "source_url": None,
        "week_start": None, "week_end": None, "publication_date": None,
        "unit": None, "short_net": None, "long_net": None, "equity_net": None,
        "detail": "暂未接入该终点市场的周度实际净买入数据。",
    }
    if destination != "JP":
        return flow
    week_start = signal_date - timedelta(days=(signal_date.weekday() + 1) % 7)
    week_end = week_start + timedelta(days=6)
    week_key = week_end.isoformat()
    published = data.get("weeks", {}).get(week_key)
    release = data.get("schedule", {}).get(week_key)
    flow.update(
        source=MOF_SOURCE,
        source_url=MOF_SOURCE_URL,
        week_start=week_start.isoformat(),
        week_end=week_key,
        publication_date=release,
        unit="亿日元",
        detail="该统计周暂无可用公布值。",
    )
    if release and datetime.combine(_date_key(release), MOF_RELEASE_TIME) > now:
        flow.update(status="pending", source_url=MOF_SCHEDULE_URL, detail="按日本财务省日程待发布（日本时间 08:50）。")
    elif published:
        flow.update(
            {field: published[field] for field in FLOW_FIELDS},
            status="published",
            detail="非居民净买入日本发行的证券，含国债及其他债券。统计口径为周度汇总。",
        )
    elif not release and datetime.combine(week_end + timedelta(days=5), MOF_RELEASE_TIME) > now:
        flow.update(status="pending", source_url=MOF_SCHEDULE_URL, detail="尚在通常发布窗口内，具体发布日期待确认。")
    elif release:
        flow.update(detail="计划发布时点已过，当前数据源尚无该周可用数值。")
    return flow


def attach_route_market_flows(payload: dict[str, Any], flow_data: dict[str, Any], *, now: datetime) -> None:
    tokyo_now = _tokyo_now(now)
    for group in payload["groups"]:
        for frequency in ("daily", "weekly"):
            for window in group[frequency]:
                signal_date = _date_key(window["signal_date"])
                for route in window["routes"]:
                    route["flow"] = _flow_for_route(route["destination"], signal_date, flow_data, tokyo_now)
