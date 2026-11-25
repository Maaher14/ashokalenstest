#!/usr/bin/env bash
# Run on the Ubuntu EC2 host: sudo bash deploy/install.sh
set -euo pipefail
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${SUDO_USER:-ubuntu}"
if [ "$EUID" -ne 0 ]; then echo 'Run with sudo bash deploy/install.sh'; exit 1; fi
if [ "$APP_USER" = root ]; then echo 'Run through sudo from your ordinary ubuntu user.'; exit 1; fi
apt-get update
apt-get install -y python3-venv nginx ffmpeg
install -d -o "$APP_USER" -g "$APP_USER" -m 700 /var/lib/ashoka-lens
if [ ! -f /etc/ashoka-lens.env ]; then
    cat > /etc/ashoka-lens.env <<'ENV'
PRODUCTION=1
DEMO_MODE=0
STORAGE=s3
LENS_DATA=/var/lib/ashoka-lens
S3_BUCKET=ashoka-lens-media
AWS_REGION=ap-southeast-2
GOOGLE_CLIENT_ID=176502342331-4ge9mjsg63u0mvrfic6bulrplrj5jdt9.apps.googleusercontent.com
ENV
    chmod 600 /etc/ashoka-lens.env
fi
sudo -u "$APP_USER" python3 -m venv "$APP_ROOT/.venv"
sudo -u "$APP_USER" "$APP_ROOT/.venv/bin/python" -m pip install -r "$APP_ROOT/requirements.txt"
# A stopped service has no in-flight mutations when recovery runs.
systemctl stop ashoka-lens.service 2>/dev/null || true
cat > /etc/systemd/system/ashoka-lens.service <<UNIT
[Unit]
Description=Ashoka Lens
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_ROOT
EnvironmentFile=/etc/ashoka-lens.env
ExecStartPre=$APP_ROOT/.venv/bin/flask --app app recover
ExecStart=$APP_ROOT/.venv/bin/gunicorn --workers 1 --threads 4 --timeout 180 --bind 127.0.0.1:8001 app:app
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
# Forwarded headers are set by Nginx, not trusted directly from a browser.
cat > /etc/nginx/sites-available/ashoka-lens <<'NGINX'
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 21M;
    client_body_timeout 120s;
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
        proxy_request_buffering on;
    }
}
NGINX
ln -sfn /etc/nginx/sites-available/ashoka-lens /etc/nginx/sites-enabled/ashoka-lens
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now ashoka-lens
systemctl enable nginx
systemctl reload nginx
sleep 2
if ! curl --fail --silent http://127.0.0.1:8001/health; then
    journalctl -u ashoka-lens -n 35 --no-pager
    exit 1
fi
echo
echo 'Ashoka Lens is running. Open your CloudFront HTTPS address.'
echo 'Configuration: /etc/ashoka-lens.env. Database and session key: /var/lib/ashoka-lens.'
