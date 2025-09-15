#!/usr/bin/env bash
set -euo pipefail

APP_NAME="wol-proxy"
INSTALL_DIR="/opt/${APP_NAME}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

if [[ $(id -u) -ne 0 ]]; then
  echo "[ERROR] Bitte als root ausführen: sudo ./install.sh"
  exit 1
fi

echo "[1/5] Pakete installieren (python3, iproute2, arping, curl)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv iproute2 iputils-ping arping curl

echo "[2/6] Dateien nach ${INSTALL_DIR} kopieren"
rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
cp -a src "${INSTALL_DIR}/"
cp -a README.md "${INSTALL_DIR}/" || true
mkdir -p /opt/wol-proxy/bin
cp -a bin/wol-proxy-setup /opt/wol-proxy/bin/
chmod +x /opt/wol-proxy/bin/wol-proxy-setup
ln -sf /opt/wol-proxy/bin/wol-proxy-setup /usr/local/bin/wol-proxy-setup

echo "[3/6] Ersteinrichtung (Terminal Setup)"
if [[ ! -f /opt/wol-proxy/config.json ]]; then
  /usr/bin/env python3 /opt/wol-proxy/src/wol_proxy/setup_tui.py || true
fi

echo "[4/6] systemd Service installieren"
cat > "${SERVICE_FILE}" <<'UNIT'
[Unit]
Description=WOL Proxy (Minecraft & Satisfactory)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=2
User=root
ExecStart=/usr/bin/env python3 /opt/wol-proxy/src/wol_proxy/main.py --daemon --config /opt/wol-proxy/config.json
WorkingDirectory=/opt/wol-proxy
AmbientCapabilities=
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable "${APP_NAME}.service"

echo "[5/6] Erster Start"
systemctl restart "${APP_NAME}.service"

echo "[6/6] Fertig"
echo "- Setup erneut starten: sudo wol-proxy-setup"
echo "- Service-Logs: sudo journalctl -u ${APP_NAME} -f"
