#!/usr/bin/env python3
"""Fetch cross-checked government bond yield rows from server-safe sources."""

from __future__ import annotations

import csv
import json
import re
import time
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from fetch_japan_bond_ohlc import close_only_row
from fetch_japan_bond_ohlc import row_from_tradingeconomics_quote_html


CHINAMONEY_CURVE_DATA_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/ClsYldCurvCurvData"
CHINAMONEY_CURVE_XML_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/ClsYldCurvXml"
CHINAMONEY_REFERER = "https://www.chinamoney.com.cn/english/bmkycvcyc/"
TRADINGECONOMICS_BASE_URL = "https://tradingeconomics.com"
BOK_ECOS_BASE_URL = "https://ecos.bok.or.kr/api"
SMBS_KORIBOR_URL = "http://www.smbs.biz/Eng/Funds/Koribor.jsp"

CHINAMONEY_TERMS = {
    "0.083": "1M",
    "0.25": "3M",
    "0.5": "6M",
    "1": "1Y",
    "2": "2Y",
    "3": "3Y",
    "5": "5Y",
    "7": "7Y",
    "10": "10Y",
    "30": "30Y",
}

BOK_ECOS_MARKET_RATE_ITEMS = {
    "KORIBOR_3M": "010150000",
    "KORIBOR_6M": "010151000",
    "MSB_91D": "010400000",
    "CD_91D": "010502000",
}

BUNDESBANK_CODES = {
    "2Y": "D.REN.EUR.A610.000000WT0202.A",
    "5Y": "D.REN.EUR.A620.000000WT0505.A",
    "7Y": "D.REN.EUR.A607.000000WT7070.A",
    "10Y": "D.REN.EUR.A630.000000WT1010.A",
    "30Y": "D.REN.EUR.A640.000000WT3030.A",
}

BUNDESBANK_TERM_STRUCTURE_CODES = {
    "1Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R01XX.R.A.A._Z._Z.A",
    "3Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R03XX.R.A.A._Z._Z.A",
}

TRADING_ECONOMICS_COUNTRY_SLUGS = {
    "germany": {
        "3M": "3-month-bill-yield",
        "6M": "6-month-bill-yield",
        "1Y": "52-week-bill-yield",
        "3Y": "3-year-note-yield",
    },
    "south-korea": {
        "1Y": "52-week-bill-yield",
        "2Y": "2-year-note-yield",
        "3Y": "3-year-note-yield",
        "5Y": "5-year-note-yield",
        "10Y": "government-bond-yield",
        "30Y": "30-year-bond-yield",
    },
}


def rows_by_tenor_from_chinamoney_payload(payload_text: str, date_text: str) -> dict[str, dict[str, Any]]:
    payload = json.loads(payload_text)
    xml_text = payload.get("data", {}).get("dataXml", "")
    if not xml_text:
        return {}

    root = ET.fromstring(xml_text)
    xaxis = root.find("xaxis")
    graph = root.find("graphs/graph")
    if xaxis is None or graph is None:
        return {}

    xid_to_term = {value.attrib.get("xid", ""): (value.text or "").strip() for value in xaxis.findall("value")}
    rows: dict[str, dict[str, Any]] = {}
    for value in graph.findall("value"):
        tenor = CHINAMONEY_TERMS.get(xid_to_term.get(value.attrib.get("xid", ""), ""))
        if not tenor or not value.text:
            continue
        rows[tenor] = close_only_row(date_text, float(value.text))
    return rows


def chinamoney_curve_date(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


def fetch_chinamoney_rows_by_tenor_for_date(day: date) -> dict[str, dict[str, Any]]:
    payload = post_json(
        CHINAMONEY_CURVE_XML_URL,
        {
            "lang": "EN",
            "bondType": "CYCC000",
            "interestRateDate": chinamoney_curve_date(day),
            "maturityYield": "1",
            "currentYield": "",
            "futureYield": "",
        },
    )
    return rows_by_tenor_from_chinamoney_payload(json.dumps(payload), day.isoformat())


def fetch_chinamoney_history_rows_by_tenor(start_day: date, end_day: date, sleep_sec: float = 0.0) -> dict[str, list[dict[str, Any]]]:
    rows_by_tenor: dict[str, list[dict[str, Any]]] = {}
    current = start_day
    while current <= end_day:
        if current.weekday() < 5:
            for tenor, row in fetch_chinamoney_rows_by_tenor_for_date(current).items():
                rows_by_tenor.setdefault(tenor, []).append(row)
            if sleep_sec:
                time.sleep(sleep_sec)
        current += timedelta(days=1)
    return rows_by_tenor


def decode_smbs_obfuscated_html(html: str) -> str:
    def decode_payload(match: re.Match[str]) -> str:
        encoded = match.group(2)
        return re.sub(r"%_[A-Z]([0-9A-Fa-f]{2})", lambda item: chr(int(item.group(1), 16)), encoded)

    return re.sub(r"<script>\s*d\d\(\s*([\"'])(.*?)\1\s*\);\s*</script>", decode_payload, html, flags=re.DOTALL)


def rows_by_tenor_from_smbs_koribor_html(html: str) -> dict[str, list[dict[str, Any]]]:
    decoded = decode_smbs_obfuscated_html(html)
    table_match = re.search(
        r"<caption>\s*Daily KORIBOR result\s*</caption>.*?<thead>(?P<thead>.*?)</thead>.*?<tbody>(?P<tbody>.*?)</tbody>",
        decoded,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not table_match:
        return {}

    headers = [
        re.sub(r"\s+", " ", re.sub(r"<.*?>", " ", cell)).strip()
        for cell in re.findall(r"<th[^>]*>(.*?)</th>", table_match.group("thead"), flags=re.IGNORECASE | re.DOTALL)
    ][1:]
    rows_by_tenor: dict[str, list[dict[str, Any]]] = {header: [] for header in headers if header}
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", table_match.group("tbody"), flags=re.IGNORECASE | re.DOTALL):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<.*?>", " ", cell)).strip()
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.IGNORECASE | re.DOTALL)
        ]
        if len(cells) < len(headers) + 1:
            continue
        try:
            row_date = datetime.strptime(cells[0], "%Y/%m/%d").date().isoformat()
        except ValueError:
            continue
        for tenor, value in zip(headers, cells[1:]):
            if not tenor or not value or value == "-":
                continue
            try:
                close = float(value)
            except ValueError:
                continue
            row = close_only_row(row_date, close)
            row["source"] = "Seoul Money Brokerage Services KORIBOR fixing"
            rows_by_tenor.setdefault(tenor, []).append(row)

    return {tenor: sorted(rows, key=lambda row: row["date"]) for tenor, rows in rows_by_tenor.items() if rows}


def fetch_smbs_koribor_rows_by_tenor(start_day: date, end_day: date) -> dict[str, list[dict[str, Any]]]:
    form = {
        "StrSch_Year": f"{end_day.year}",
        "StrSch_Month": f"{end_day.month:02d}",
        "StrSch_Day": f"{end_day.day:02d}",
        "StrSch_sYear": f"{start_day.year}",
        "StrSch_sMonth": f"{start_day.month:02d}",
        "StrSch_sDay": f"{start_day.day:02d}",
        "StrSch_eYear": f"{end_day.year}",
        "StrSch_eMonth": f"{end_day.month:02d}",
        "StrSch_eDay": f"{end_day.day:02d}",
        "StrSch_tsYear": f"{start_day.year}",
        "StrSch_tsMonth": f"{start_day.month:02d}",
        "StrSch_tsDay": f"{start_day.day:02d}",
        "StrSch_teYear": f"{end_day.year}",
        "StrSch_teMonth": f"{end_day.month:02d}",
        "StrSch_teDay": f"{end_day.day:02d}",
        "StrSchFull": end_day.strftime("%Y.%m.%d"),
        "StrSchFull2": start_day.strftime("%Y.%m.%d"),
        "StrSchFull3": end_day.strftime("%Y.%m.%d"),
        "StrSchFull4": start_day.strftime("%Y.%m.%d"),
        "StrSchFull5": end_day.strftime("%Y.%m.%d"),
    }
    request = Request(
        SMBS_KORIBOR_URL,
        data=urlencode(form).encode("utf-8"),
        method="POST",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    html = urlopen(request, timeout=60).read().decode("euc-kr", "ignore")
    return rows_by_tenor_from_smbs_koribor_html(html)


def rows_from_bok_ecos_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in payload.get("StatisticSearch", {}).get("row", []):
        try:
            row_date = datetime.strptime(str(item.get("TIME", "")), "%Y%m%d").date().isoformat()
            close = float(item.get("DATA_VALUE", ""))
        except ValueError:
            continue
        rows.append(close_only_row(row_date, close))
    return rows


def fetch_bok_ecos_rows(item_code: str, start_day: date, end_day: date, api_key: str = "sample") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start_row = 1
    while True:
        end_row = start_row + 9
        url = (
            f"{BOK_ECOS_BASE_URL}/StatisticSearch/{api_key}/json/en/{start_row}/{end_row}"
            f"/817Y002/D/{start_day:%Y%m%d}/{end_day:%Y%m%d}/{item_code}"
        )
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        payload = json.loads(urlopen(request, timeout=30).read().decode("utf-8", "ignore"))
        batch = rows_from_bok_ecos_payload(payload)
        if not batch:
            break
        rows.extend(batch)
        total_count = int(payload.get("StatisticSearch", {}).get("list_total_count", len(rows)))
        if len(rows) >= total_count:
            break
        start_row += 10
    return rows


def rows_from_bundesbank_csv(csv_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in csv.reader(StringIO(csv_text)):
        if len(row) < 2 or not row[0][:4].isdigit() or row[1] in {"", "."}:
            continue
        try:
            rows.append(close_only_row(row[0], float(row[1])))
        except ValueError:
            continue
    return rows


def post_json(url: str, data: dict[str, str] | None = None) -> dict[str, Any]:
    encoded = urlencode(data or {}).encode("utf-8")
    request = Request(
        url,
        data=encoded,
        method="POST",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": CHINAMONEY_REFERER,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    return json.loads(urlopen(request, timeout=30).read().decode("utf-8", "ignore"))


def fetch_chinamoney_rows_by_tenor() -> dict[str, list[dict[str, Any]]]:
    metadata = post_json(CHINAMONEY_CURVE_DATA_URL)
    data = metadata.get("data", {})
    date_text = data.get("interestRateDateCN", "")
    date_en = data.get("interestRateDateEN", "")
    if not date_text or not date_en:
        return {}

    payload = post_json(
        CHINAMONEY_CURVE_XML_URL,
        {
            "lang": "EN",
            "bondType": "CYCC000",
            "interestRateDate": date_en,
            "maturityYield": "1",
            "currentYield": "",
            "futureYield": "",
        },
    )
    return {tenor: [row] for tenor, row in rows_by_tenor_from_chinamoney_payload(json.dumps(payload), date_text).items()}


def fetch_bundesbank_rows(code: str) -> list[dict[str, Any]]:
    url = f"https://api.statistiken.bundesbank.de/rest/data/BBSSY/{code}?format=csv&lang=en"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    text = urlopen(request, timeout=30).read().decode("utf-8-sig", "ignore")
    return rows_from_bundesbank_csv(text)


def fetch_bundesbank_term_structure_rows(code: str) -> list[dict[str, Any]]:
    url = f"https://api.statistiken.bundesbank.de/rest/data/BBSIS/{code}?format=csv&lang=en"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    text = urlopen(request, timeout=30).read().decode("utf-8-sig", "ignore")
    return rows_from_bundesbank_csv(text)


def fetch_tradingeconomics_country_latest_row(country_slug: str, tenor_slug: str) -> dict[str, Any] | None:
    request = Request(f"{TRADINGECONOMICS_BASE_URL}/{country_slug}/{tenor_slug}", headers={"User-Agent": "Mozilla/5.0"})
    html = urlopen(request, timeout=30).read().decode("utf-8", "ignore")
    return row_from_tradingeconomics_quote_html(html)
