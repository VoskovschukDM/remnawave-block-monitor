#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

SERVICE_NAME="remnawave-block-monitor"
SERVICE_USER="remnawave-monitor"
APP_DIR="/opt/remnawave-block-monitor"
CONFIG_DIR="/etc/remnawave-block-monitor"
STATE_DIR="/var/lib/remnawave-block-monitor"
LOG_DIR="/var/log/remnawave-block-monitor"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
BIN_PATH="/usr/local/bin/remnawave-block-monitor"

# Override the source repository when maintaining a fork:
# curl .../install.sh | sudo REMNAWAVE_MONITOR_REPOSITORY=owner/repo bash
REPOSITORY="${REMNAWAVE_MONITOR_REPOSITORY:-VoskovschukDM/remnawave-block-monitor}"
REPOSITORY_REF="${REMNAWAVE_MONITOR_REF:-main}"

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

info() {
  echo "[INFO] $*"
}

[[ "${EUID}" -eq 0 ]] || die "Run this installer as root (sudo)."
[[ -r /etc/os-release ]] || die "Cannot detect Linux distribution (/etc/os-release is missing)."
command -v systemctl >/dev/null 2>&1 || die "systemd is required."

# shellcheck disable=SC1091
. /etc/os-release

install_dependencies() {
  case "${ID:-}:${ID_LIKE:-}" in
    debian:*|ubuntu:*|*:debian*)
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 ca-certificates curl tar
      ;;
    fedora:*|rhel:*|rocky:*|almalinux:*|centos:*|*:rhel*|*:fedora*)
      local manager="dnf"
      command -v dnf >/dev/null 2>&1 || manager="yum"
      "${manager}" install -y python3 ca-certificates curl tar
      ;;
    opensuse*:*|sles:*|*:suse*)
      zypper --non-interactive install python3 ca-certificates curl tar
      ;;
    arch:*|manjaro:*|*:arch*)
      pacman -Sy --needed --noconfirm python ca-certificates curl tar
      ;;
    *)
      die "Unsupported distribution: ${PRETTY_NAME:-${ID:-unknown}}. Install Python 3.10+, curl, tar and CA certificates manually."
      ;;
  esac
}

install_dependencies

command -v python3 >/dev/null 2>&1 || die "python3 was not installed."
python3 - <<'PY' || die "Python 3.10 or newer is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
SOURCE_DIR="${SCRIPT_DIR}"
TEMP_DIR=""

cleanup() {
  if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
    rm -rf -- "${TEMP_DIR}"
  fi
}
trap cleanup EXIT

if [[ ! -f "${SOURCE_DIR}/monitor.py" || ! -d "${SOURCE_DIR}/remnawave_block_monitor" ]]; then
  TEMP_DIR="$(mktemp -d -t remnawave-monitor.XXXXXXXX)"
  ARCHIVE="${TEMP_DIR}/source.tar.gz"
  info "Downloading ${REPOSITORY}@${REPOSITORY_REF}..."
  curl --fail --silent --show-error --location --retry 3 \
    "https://github.com/${REPOSITORY}/archive/refs/heads/${REPOSITORY_REF}.tar.gz" \
    --output "${ARCHIVE}"
  tar -xzf "${ARCHIVE}" -C "${TEMP_DIR}"
  SOURCE_DIR="$(find "${TEMP_DIR}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
fi

[[ -f "${SOURCE_DIR}/monitor.py" ]] || die "Source tree is incomplete (monitor.py missing)."
[[ -f "${SOURCE_DIR}/systemd/${SERVICE_NAME}.service" ]] || die "Source tree is incomplete (systemd unit missing)."

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  NOLOGIN="$(command -v nologin || true)"
  [[ -n "${NOLOGIN}" ]] || NOLOGIN="/usr/sbin/nologin"
  useradd --system --user-group --home-dir "${STATE_DIR}" --shell "${NOLOGIN}" "${SERVICE_USER}"
fi

install -d -m 0755 -o root -g root "${APP_DIR}"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${CONFIG_DIR}"
install -d -m 0750 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STATE_DIR}" "${LOG_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${STATE_DIR}" "${LOG_DIR}"

systemctl stop "${SERVICE_NAME}.service" >/dev/null 2>&1 || true

# Only application-owned paths are replaced. Configuration and state are outside APP_DIR.
rm -rf -- "${APP_DIR}/remnawave_block_monitor"
cp -a -- "${SOURCE_DIR}/remnawave_block_monitor" "${APP_DIR}/remnawave_block_monitor"
install -m 0755 -o root -g root "${SOURCE_DIR}/monitor.py" "${APP_DIR}/monitor.py"
install -m 0644 -o root -g root "${SOURCE_DIR}/pyproject.toml" "${APP_DIR}/pyproject.toml"
find "${APP_DIR}/remnawave_block_monitor" -type d -exec chmod 0755 {} +
find "${APP_DIR}/remnawave_block_monitor" -type f -exec chmod 0644 {} +

if [[ ! -e "${CONFIG_DIR}/config.env" ]]; then
  install -m 0640 -o root -g "${SERVICE_USER}" "${SOURCE_DIR}/config.env.example" "${CONFIG_DIR}/config.env"
  info "Created ${CONFIG_DIR}/config.env"
else
  chown root:"${SERVICE_USER}" "${CONFIG_DIR}/config.env"
  chmod 0640 "${CONFIG_DIR}/config.env"
  info "Preserved existing ${CONFIG_DIR}/config.env"
fi

if [[ ! -e "${CONFIG_DIR}/targets.txt" ]]; then
  install -m 0640 -o root -g "${SERVICE_USER}" "${SOURCE_DIR}/targets.txt.example" "${CONFIG_DIR}/targets.txt"
  info "Created ${CONFIG_DIR}/targets.txt"
else
  chown root:"${SERVICE_USER}" "${CONFIG_DIR}/targets.txt"
  chmod 0640 "${CONFIG_DIR}/targets.txt"
  info "Preserved existing ${CONFIG_DIR}/targets.txt"
fi

install -m 0644 -o root -g root "${SOURCE_DIR}/systemd/${SERVICE_NAME}.service" "${UNIT_PATH}"
ln -sfn "${APP_DIR}/monitor.py" "${BIN_PATH}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"

info "Installation/update complete. Add targets to ${CONFIG_DIR}/targets.txt."
systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
