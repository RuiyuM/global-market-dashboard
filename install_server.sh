#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/RuiyuM/global-market-dashboard.git}"
APP_DIR="${APP_DIR:-/opt/global-market-dashboard}"
SERVICE_USER="${SERVICE_USER:-globaldash}"
UPDATE_CALENDAR="${UPDATE_CALENDAR:-Mon..Fri *-*-* 16:10:00 America/New_York}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: curl -fsSL ... | sudo bash" >&2
  exit 1
fi

NGINX_CONFIG=""
if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y git python3 curl nginx ca-certificates
  NGINX_CONFIG="/etc/nginx/sites-available/global-market-dashboard"
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y git python3 curl ca-certificates
  dnf --disableexcludes=all install -y nginx
  NGINX_CONFIG="/etc/nginx/conf.d/global-market-dashboard.conf"
else
  echo "This installer supports apt or dnf systems." >&2
  exit 1
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  NOLOGIN_SHELL="$(command -v nologin || true)"
  useradd --system --home "${APP_DIR}" --shell "${NOLOGIN_SHELL:-/sbin/nologin}" "${SERVICE_USER}"
fi

if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" pull --ff-only
else
  rm -rf "${APP_DIR}"
  git clone "${REPO_URL}" "${APP_DIR}"
fi

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"
chmod +x "${APP_DIR}/update_market_dashboard.sh"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 700 "${APP_DIR}/.private"

cat >/etc/systemd/system/global-market-dashboard-update.service <<EOF
[Unit]
Description=Update Global Market Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
Environment=MARKET_SKIP_INVESTING=1
EnvironmentFile=-${APP_DIR}/.private/policy_news.env
ExecStart=${APP_DIR}/update_market_dashboard.sh
EOF

cat >/etc/systemd/system/global-market-dashboard-update.timer <<EOF
[Unit]
Description=Daily Global Market Dashboard update

[Timer]
OnCalendar=${UPDATE_CALENDAR}
Persistent=true
Unit=global-market-dashboard-update.service

[Install]
WantedBy=timers.target
EOF

NGINX_TEMPLATE="${APP_DIR}/ops/nginx/global-market-dashboard.conf"
if [[ ! -f "${NGINX_TEMPLATE}" ]]; then
  echo "Missing tracked Nginx template: ${NGINX_TEMPLATE}" >&2
  exit 1
fi
sed "s|__APP_DIR__|${APP_DIR}|g" "${NGINX_TEMPLATE}" >"${NGINX_CONFIG}"

if [[ "${NGINX_CONFIG}" == /etc/nginx/sites-available/* ]]; then
  rm -f /etc/nginx/sites-enabled/default
  ln -sf "${NGINX_CONFIG}" /etc/nginx/sites-enabled/global-market-dashboard
else
  rm -f /etc/nginx/conf.d/default.conf
fi

systemctl daemon-reload
systemctl enable --now global-market-dashboard-update.timer
systemctl start global-market-dashboard-update.service
nginx -t
systemctl enable --now nginx
systemctl reload nginx

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp || true
fi

PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org || hostname -I | awk '{print $1}')"
echo
echo "Global Market Dashboard installed."
echo "Open: http://${PUBLIC_IP}/"
echo "App dir: ${APP_DIR}"
echo "Timer: systemctl list-timers global-market-dashboard-update.timer"
