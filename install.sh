#!/usr/bin/env bash
set -euo pipefail

APP_NAME="wol-proxy"
INSTALL_DIR="/opt/${APP_NAME}"
BIN_DIR="${INSTALL_DIR}/bin"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

if [[ $(id -u) -ne 0 ]]; then
  echo "[ERROR] Please run as root: sudo ./install.sh"
  exit 1
fi

echo "[1/6] Installing packages (python3, iproute2, arping, curl)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv iproute2 iputils-ping arping curl

echo "[2/6] Syncing files into ${INSTALL_DIR}"
rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
cp -a src "${INSTALL_DIR}/"
cp -a README.md "${INSTALL_DIR}/" || true
mkdir -p "${BIN_DIR}"
cp -a bin/wol-proxy-setup "${BIN_DIR}/"
chmod +x "${BIN_DIR}/wol-proxy-setup"
ln -sf "${BIN_DIR}/wol-proxy-setup" /usr/local/bin/wol-proxy-setup

echo "[3/6] Running first-time terminal setup"
if [[ ! -f "/opt/${APP_NAME}/config.json" ]]; then
  /usr/bin/env PYTHONPATH="/opt/${APP_NAME}/src" python3 -m wol_proxy.setup_tui || true
fi

echo "[4/6] Installing systemd service"
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

echo "[5/6] Starting service"
systemctl restart "${APP_NAME}.service"

echo "[6/6] Done"
echo "- Re-run setup: sudo wol-proxy-setup"
echo "- Follow logs: sudo journalctl -u ${APP_NAME} -f"
