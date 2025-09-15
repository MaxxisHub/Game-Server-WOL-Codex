#!/usr/bin/env bash
set -euo pipefail

APP_NAME="wol-proxy"
INSTALL_DIR="/opt/${APP_NAME}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

if [[ $(id -u) -ne 0 ]]; then
  echo "[ERROR] Bitte als root ausführen: sudo ./uninstall.sh"
  exit 1
fi

systemctl stop "${APP_NAME}.service" || true
systemctl disable "${APP_NAME}.service" || true
rm -f "${SERVICE_FILE}" || true
systemctl daemon-reload || true
rm -rf "${INSTALL_DIR}" || true

echo "Deinstallation abgeschlossen."

