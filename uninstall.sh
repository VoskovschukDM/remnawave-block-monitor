#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="remnawave-block-monitor"
SERVICE_USER="remnawave-monitor"
APP_DIR="/opt/remnawave-block-monitor"
CONFIG_DIR="/etc/remnawave-block-monitor"
STATE_DIR="/var/lib/remnawave-block-monitor"
LOG_DIR="/var/log/remnawave-block-monitor"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
BIN_PATH="/usr/local/bin/remnawave-block-monitor"
PURGE=false

for argument in "$@"; do
  case "${argument}" in
    --purge) PURGE=true ;;
    --yes) : ;;
    -h|--help)
      echo "Usage: sudo ./uninstall.sh [--purge] [--yes]"
      echo "By default config and state are preserved. --purge removes them."
      exit 0
      ;;
    *) echo "Unknown option: ${argument}" >&2; exit 2 ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || { echo "[ERROR] Run as root (sudo)." >&2; exit 1; }

safe_remove_tree() {
  case "$1" in
    /opt/remnawave-block-monitor|/etc/remnawave-block-monitor|/var/lib/remnawave-block-monitor|/var/log/remnawave-block-monitor)
      rm -rf -- "$1"
      ;;
    *) echo "[ERROR] Refusing unsafe path: $1" >&2; exit 1 ;;
  esac
}

systemctl disable --now "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
rm -f -- "${UNIT_PATH}" "${BIN_PATH}"
safe_remove_tree "${APP_DIR}"
safe_remove_tree "${LOG_DIR}"
systemctl daemon-reload
systemctl reset-failed "${SERVICE_NAME}.service" >/dev/null 2>&1 || true

if ${PURGE}; then
  safe_remove_tree "${CONFIG_DIR}"
  safe_remove_tree "${STATE_DIR}"
  echo "[INFO] Application, config, state, and logs removed."
else
  if [[ -d "${CONFIG_DIR}" ]]; then chown -R root:root "${CONFIG_DIR}"; fi
  if [[ -d "${STATE_DIR}" ]]; then chown -R root:root "${STATE_DIR}"; fi
  echo "[INFO] Application removed. Config and state were preserved."
  echo "[INFO] Use --purge to remove ${CONFIG_DIR} and ${STATE_DIR}."
fi

if id "${SERVICE_USER}" >/dev/null 2>&1; then
  userdel "${SERVICE_USER}" >/dev/null 2>&1 || true
fi
