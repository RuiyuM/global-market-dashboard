from __future__ import annotations

import hashlib
import json
import ssl
from datetime import date

import market_dashboard


class DummyResponse:
    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"candles": {"columns": [], "data": []}}).encode("utf-8")


def test_moex_root_certificate_matches_pinned_fingerprint() -> None:
    pem = market_dashboard.MOEX_CA_PATH.read_text(encoding="ascii")
    der = ssl.PEM_cert_to_DER_cert(pem)

    assert hashlib.sha256(der).hexdigest() == market_dashboard.MOEX_CA_SHA256
    context = market_dashboard.moex_ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_moex_fetches_pass_the_scoped_ssl_context(monkeypatch) -> None:
    scoped_context = object()
    seen_contexts: list[object] = []

    monkeypatch.setattr(market_dashboard, "moex_ssl_context", lambda: scoped_context)

    def fake_urlopen(_request, *, timeout: int, context: object) -> DummyResponse:
        assert timeout == 30
        seen_contexts.append(context)
        return DummyResponse()

    monkeypatch.setattr(market_dashboard, "urlopen", fake_urlopen)

    assert market_dashboard.fetch_moex_rubcny_ohlc("CNYRUB_TOM", date(2026, 11, 20), date(2026, 11, 23)) == []
    assert market_dashboard.fetch_moex_index_ohlc("IMOEX", date(2026, 11, 20), date(2026, 11, 23)) == []
    assert seen_contexts == [scoped_context, scoped_context]
