#!/usr/bin/env python3
"""Static invariants for the production Nginx configuration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG = (ROOT / "ops" / "nginx" / "global-market-dashboard.conf").read_text(encoding="utf-8")
SSHD_CONFIG = (ROOT / "ops" / "ssh" / "00-dashboard-hardening.conf").read_text(
    encoding="utf-8"
)
CERTBOT_SERVICE = (
    ROOT / "ops" / "systemd" / "dashboard-certbot-renew.service"
).read_text(encoding="utf-8")
CERTBOT_TIMER = (
    ROOT / "ops" / "systemd" / "dashboard-certbot-renew.timer"
).read_text(encoding="utf-8")
INSTALLER = (ROOT / "install_server.sh").read_text(encoding="utf-8")


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


def test_quant_fund_page_and_snapshot_are_public_read_only_resources() -> None:
    assert "location = /quant_fund.html {" in CONFIG
    assert "location = /quant_fund_snapshot.json {" in CONFIG
    assert "auth_basic" not in CONFIG
    assert "quant_fund.htpasswd" not in CONFIG
    assert CONFIG.count('add_header Cache-Control "private, no-store" always;') == 2


def test_dashboard_nginx_uses_trusted_ip_https() -> None:
    assert "listen 443 ssl default_server;" in CONFIG
    assert "ssl_certificate /etc/letsencrypt/live/__PUBLIC_IP__/fullchain.pem;" in CONFIG
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in CONFIG
    assert 'Strict-Transport-Security "max-age=31536000" always;' in CONFIG
    assert "return 308 https://__PUBLIC_IP__/;" in CONFIG
    assert "location ^~ /.well-known/acme-challenge/" in CONFIG


def test_dashboard_nginx_root_is_rendered_by_installer() -> None:
    assert "root __APP_DIR__/dashboard;" in CONFIG
    assert "server_name __PUBLIC_IP__" in CONFIG
    assert 's|__APP_DIR__|${APP_DIR}|g' in INSTALLER
    assert 's|__PUBLIC_IP__|${PUBLIC_IP}|g' in INSTALLER


def test_dashboard_sshd_keeps_key_login_and_rejects_passwords() -> None:
    assert "PermitRootLogin prohibit-password" in SSHD_CONFIG
    assert "PasswordAuthentication no" in SSHD_CONFIG
    assert "PubkeyAuthentication yes" in SSHD_CONFIG
    assert "PermitEmptyPasswords no" in SSHD_CONFIG


def test_dashboard_sshd_limits_authentication_abuse() -> None:
    assert "MaxAuthTries 3" in SSHD_CONFIG
    assert "LoginGraceTime 30" in SSHD_CONFIG
    assert "X11Forwarding no" in SSHD_CONFIG


def test_dashboard_ip_certificate_renews_and_reloads_nginx() -> None:
    assert "/opt/certbot/bin/certbot renew" in CERTBOT_SERVICE
    assert "--no-random-sleep-on-renew" in CERTBOT_SERVICE
    assert "dashboard-certbot-reload-nginx" in CERTBOT_SERVICE
    assert "OnCalendar=*-*-* 00,12:17:00" in CERTBOT_TIMER
    assert "Persistent=true" in CERTBOT_TIMER


def test_dashboard_fallback_update_precedes_local_post_close_patch() -> None:
    assert (
        'UPDATE_CALENDAR="${UPDATE_CALENDAR:-Mon..Fri *-*-* 16:10:00 America/New_York}"'
        in INSTALLER
    )
