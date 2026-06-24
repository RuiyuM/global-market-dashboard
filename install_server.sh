#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/RuiyuM/global-market-dashboard.git}"
APP_DIR="${APP_DIR:-/opt/global-market-dashboard}"
SERVICE_USER="${SERVICE_USER:-globaldash}"
UPDATE_TIME="${UPDATE_TIME:-07:30:00}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: curl -fsSL ... | sudo bash" >&2
  exit 1
fi

NGINX_SITE_TARGET=""

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y git python3 curl nginx ca-certificates
  NGINX_SITE_TARGET="/etc/nginx/sites-available/global-market-dashboard"
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y git python3 curl nginx ca-certificates
  NGINX_SITE_TARGET="/etc/nginx/conf.d/global-market-dashboard.conf"
elif command -v yum >/dev/null 2>&1; then
  yum install -y git python3 curl nginx ca-certificates
  NGINX_SITE_TARGET="/etc/nginx/conf.d/global-market-dashboard.conf"
else
  echo "This installer supports Debian/Ubuntu apt, OpenCloudOS/CentOS/RHEL dnf, or yum systems." >&2
  exit 1
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  NOLOGIN_SHELL="$(command -v nologin || true)"
  if [[ -z "${NOLOGIN_SHELL}" ]]; then
    NOLOGIN_SHELL="/sbin/nologin"
  fi
  useradd --system --home "${APP_DIR}" --shell "${NOLOGIN_SHELL}" "${SERVICE_USER}"
fi

PYTHON_BIN="$(command -v python3)"

if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" pull --ff-only
else
  rm -rf "${APP_DIR}"
  git clone "${REPO_URL}" "${APP_DIR}"
fi

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"
chmod +x "${APP_DIR}/update_market_dashboard.sh"

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
ExecStart=${APP_DIR}/update_market_dashboard.sh
ExecStartPost=${PYTHON_BIN} ${APP_DIR}/validate_market_dashboard.py
EOF

cat >/etc/systemd/system/global-market-dashboard-update.timer <<EOF
[Unit]
Description=Daily Global Market Dashboard update

[Timer]
OnCalendar=*-*-* ${UPDATE_TIME}
Persistent=true
Unit=global-market-dashboard-update.service

[Install]
WantedBy=timers.target
EOF

cat >"${NGINX_SITE_TARGET}" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    root ${APP_DIR}/dashboard;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF

if [[ -d /etc/nginx/sites-enabled ]]; then
  rm -f /etc/nginx/sites-enabled/default
  ln -sf "${NGINX_SITE_TARGET}" /etc/nginx/sites-enabled/global-market-dashboard
fi

systemctl daemon-reload
systemctl enable --now nginx
systemctl enable --now global-market-dashboard-update.timer
systemctl start global-market-dashboard-update.service
nginx -t
systemctl reload nginx

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp || true
fi

if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-service=http || true
  firewall-cmd --reload || true
fi

PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org || hostname -I | awk '{print $1}')"
echo
echo "Global Market Dashboard installed."
echo "Open: http://${PUBLIC_IP}/"
echo "App dir: ${APP_DIR}"
echo "Timer: systemctl list-timers global-market-dashboard-update.timer"
