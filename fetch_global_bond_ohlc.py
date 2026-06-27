#!/usr/bin/env python3
"""Fetch cross-checked government bond yield rows from server-safe sources."""

from __future__ import annotations

import csv
import json
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

BUNDESBANK_CODES = {
    "2Y": "D.REN.EUR.A610.000000WT0202.A",
    "5Y": "D.REN.EUR.A620.000000WT0505.A",
    "7Y": "D.REN.EUR.A607.000000WT7070.A",
    "10Y": "D.REN.EUR.A630.000000WT1010.A",
    "30Y": "D.REN.EUR.A640.000000WT3030.A",
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


def fetch_tradingeconomics_country_latest_row(country_slug: str, tenor_slug: str) -> dict[str, Any] | None:
    request = Request(f"{TRADINGECONOMICS_BASE_URL}/{country_slug}/{tenor_slug}", headers={"User-Agent": "Mozilla/5.0"})
    html = urlopen(request, timeout=30).read().decode("utf-8", "ignore")
    return row_from_tradingeconomics_quote_html(html)
