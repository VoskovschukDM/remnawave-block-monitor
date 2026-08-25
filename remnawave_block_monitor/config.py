from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path


class ConfigError(ValueError):
    pass


def _bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false")


def _int(value: str, name: str, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return parsed


def _float(value: str, name: str, minimum: float = 0.0) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if parsed < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return parsed


def read_env_file(path: str | Path) -> dict[str, str]:
    result: dict[str, str] = {}
    file_path = Path(path)
    if not file_path.exists():
        raise ConfigError(f"Config file not found: {file_path}")
    for number, raw in enumerate(file_path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"Malformed config line {number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if not key or not key.replace("_", "").isalnum():
            raise ConfigError(f"Malformed config key on line {number}")
        result[key] = value
    return result


@dataclass(frozen=True)
class Config:
    check_interval_seconds: int = 600
    check_jitter_seconds: int = 30
    default_port: int = 443
    failures_before_alert: int = 3
    recoveries_before_alert: int = 2
    max_concurrent_targets: int = 3
    domain_check_mode: tuple[str, ...] = ("tcp", "http")
    checkhost_enabled: bool = True
    checkhost_base_url: str = "https://check-host.net"
    checkhost_ru_countries: tuple[str, ...] = ("RU",)
    checkhost_control_countries: tuple[str, ...] = ("DE", "NL", "FI", "PL")
    checkhost_ru_node_count: int = 3
    checkhost_control_node_count: int = 3
    checkhost_ru_nodes: tuple[str, ...] = ()
    checkhost_control_nodes: tuple[str, ...] = ()
    checkhost_timeout: float = 15.0
    checkhost_result_timeout: float = 30.0
    checkhost_poll_interval: float = 1.5
    checkhost_request_delay: float = 0.5
    cheburcheck_enabled: bool = True
    cheburcheck_base_url: str = "https://cheburcheck.ru/api/v1"
    cheburcheck_timeout: float = 15.0
    cheburcheck_request_delay: float = 2.2
    http_retry_attempts: int = 3
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_timeout: float = 15.0
    targets_file: str = "/etc/remnawave-block-monitor/targets.txt"
    state_file: str = "/var/lib/remnawave-block-monitor/state.json"
    log_level: str = "INFO"

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        values = read_env_file(path)

        def value(name: str, default: str) -> str:
            return os.environ.get(name, values.get(name, default))

        def csv(name: str, default: str = "") -> tuple[str, ...]:
            return tuple(item.strip() for item in value(name, default).split(",") if item.strip())

        modes = tuple(item.lower() for item in csv("DOMAIN_CHECK_MODE", "tcp,http"))
        if not modes or any(item not in {"tcp", "http"} for item in modes):
            raise ConfigError("DOMAIN_CHECK_MODE must contain tcp and/or http")
        level = value("LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError("LOG_LEVEL is invalid")
        config = cls(
            check_interval_seconds=_int(value("CHECK_INTERVAL_SECONDS", "600"), "CHECK_INTERVAL_SECONDS", 1),
            check_jitter_seconds=_int(value("CHECK_JITTER_SECONDS", "30"), "CHECK_JITTER_SECONDS"),
            default_port=_int(value("DEFAULT_PORT", "443"), "DEFAULT_PORT", 1),
            failures_before_alert=_int(value("FAILURES_BEFORE_ALERT", "3"), "FAILURES_BEFORE_ALERT", 1),
            recoveries_before_alert=_int(value("RECOVERIES_BEFORE_ALERT", "2"), "RECOVERIES_BEFORE_ALERT", 1),
            max_concurrent_targets=_int(value("MAX_CONCURRENT_TARGETS", "3"), "MAX_CONCURRENT_TARGETS", 1),
            domain_check_mode=modes,
            checkhost_enabled=_bool(value("CHECKHOST_ENABLED", "true"), "CHECKHOST_ENABLED"),
            checkhost_base_url=value("CHECKHOST_BASE_URL", "https://check-host.net").rstrip("/"),
            checkhost_ru_countries=tuple(x.upper() for x in csv("CHECKHOST_RU_COUNTRIES", "RU")),
            checkhost_control_countries=tuple(x.upper() for x in csv("CHECKHOST_CONTROL_COUNTRIES", "DE,NL,FI,PL")),
            checkhost_ru_node_count=_int(value("CHECKHOST_RU_NODE_COUNT", "3"), "CHECKHOST_RU_NODE_COUNT", 1),
            checkhost_control_node_count=_int(value("CHECKHOST_CONTROL_NODE_COUNT", "3"), "CHECKHOST_CONTROL_NODE_COUNT", 1),
            checkhost_ru_nodes=csv("CHECKHOST_RU_NODES"),
            checkhost_control_nodes=csv("CHECKHOST_CONTROL_NODES"),
            checkhost_timeout=_float(value("CHECKHOST_TIMEOUT", "15"), "CHECKHOST_TIMEOUT", 0.1),
            checkhost_result_timeout=_float(value("CHECKHOST_RESULT_TIMEOUT", "30"), "CHECKHOST_RESULT_TIMEOUT", 1.0),
            checkhost_poll_interval=_float(value("CHECKHOST_POLL_INTERVAL", "1.5"), "CHECKHOST_POLL_INTERVAL", 0.1),
            checkhost_request_delay=_float(value("CHECKHOST_REQUEST_DELAY", "0.5"), "CHECKHOST_REQUEST_DELAY"),
            cheburcheck_enabled=_bool(value("CHEBURCHECK_ENABLED", "true"), "CHEBURCHECK_ENABLED"),
            cheburcheck_base_url=value("CHEBURCHECK_BASE_URL", "https://cheburcheck.ru/api/v1").rstrip("/"),
            cheburcheck_timeout=_float(value("CHEBURCHECK_TIMEOUT", "15"), "CHEBURCHECK_TIMEOUT", 0.1),
            cheburcheck_request_delay=_float(value("CHEBURCHECK_REQUEST_DELAY", "2.2"), "CHEBURCHECK_REQUEST_DELAY"),
            http_retry_attempts=_int(value("HTTP_RETRY_ATTEMPTS", "3"), "HTTP_RETRY_ATTEMPTS", 1),
            telegram_enabled=_bool(value("TELEGRAM_ENABLED", "false"), "TELEGRAM_ENABLED"),
            telegram_bot_token=value("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=value("TELEGRAM_CHAT_ID", ""),
            telegram_timeout=_float(value("TELEGRAM_TIMEOUT", "15"), "TELEGRAM_TIMEOUT", 0.1),
            targets_file=value("TARGETS_FILE", "/etc/remnawave-block-monitor/targets.txt"),
            state_file=value("STATE_FILE", "/var/lib/remnawave-block-monitor/state.json"),
            log_level=level,
        )
        if config.default_port > 65535:
            raise ConfigError("DEFAULT_PORT must be <= 65535")
        if not config.checkhost_enabled and not config.cheburcheck_enabled:
            raise ConfigError("At least one external checker must be enabled")
        if config.telegram_enabled and (not config.telegram_bot_token or not config.telegram_chat_id):
            raise ConfigError("Telegram is enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is empty")
        return config

    def safe_summary(self) -> dict[str, object]:
        excluded = {"telegram_bot_token", "telegram_chat_id"}
        return {field.name: getattr(self, field.name) for field in fields(self) if field.name not in excluded}
