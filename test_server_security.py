#!/usr/bin/env python3
"""Static invariants for the production Nginx configuration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG = (ROOT / "ops" / "nginx" / "global-market-dashboard.conf").read_text(encoding="utf-8")


def test_dashboard_nginx_compresses_large_static_payloads() -> None:
    assert "gzip on;" in CONFIG
    assert "application/json" in CONFIG
    assert "gzip_vary on;" in CONFIG


def test_dashboard_nginx_rejects_unknown_paths_instead_of_serving_homepage() -> None:
    assert "try_files $uri $uri/ =404;" in CONFIG
    assert "try_files $uri $uri/ /index.html;" not in CONFIG


def test_dashboard_nginx_has_basic_abuse_and_browser_guards() -> None:
    assert "limit_req_zone" in CONFIG
    assert "limit_conn_zone" in CONFIG
    assert "limit_except GET" in CONFIG
    assert "X-Content-Type-Options" in CONFIG
    assert "Content-Security-Policy" in CONFIG


def test_dashboard_nginx_root_is_rendered_by_installer() -> None:
    assert "root __APP_DIR__/dashboard;" in CONFIG
