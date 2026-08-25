from __future__ import annotations

import logging
from urllib.parse import urlencode

from .config import Config
from .http_client import ExternalServiceError, JsonHttpClient
from .models import TargetResult

LOG = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, config: Config):
        self.enabled = config.telegram_enabled
        self.token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id
        self.timeout = config.telegram_timeout
        self.http = JsonHttpClient("Telegram", config.http_retry_attempts)

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        body = urlencode({"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": "true"}).encode()
        payload = self.http.request(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            self.timeout,
            method="POST",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ExternalServiceError("Telegram: API rejected sendMessage")

    def test(self) -> None:
        self.send("✅ Remnawave Block Monitor: тестовое уведомление доставлено.")


def _nodes(result: TargetResult, group: str) -> list[str]:
    lines: list[str] = []
    for node in result.checkhost.grouped_nodes(group):
        place = f"{node.city} ({node.country_code})"
        latency = f" — {node.latency_ms:.0f} ms" if node.latency_ms is not None else ""
        detail = f" — {node.detail}" if node.detail and not node.success else ""
        lines.append(f"{place}: {node.status}{latency}{detail}")
    return lines or ["нет данных"]


def _chebur(result: TargetResult) -> list[str]:
    check = result.chebur
    if not check.available:
        return ["CheburCheck: unavailable"]
    lines = [f"Blocked: {'YES' if check.blocked else 'NO'}", f"RKN domain: {check.rkn_domain or 'NO'}"]
    if check.blocked_subnets:
        lines.append(f"Blocked subnet: {', '.join(check.blocked_subnets[:5])}")
    if check.cdn_providers:
        lines.append(f"CDN providers: {', '.join(sorted(check.cdn_providers)[:5])}")
    return lines


def alert_message(result: TargetResult) -> str:
    title = "🚨 Возможная блокировка/недоступность"
    if result.analysis.verdict.value == "GLOBAL_DOWN":
        title = "🚨 Глобальная недоступность"
    lines = [
        title,
        "",
        f"Node: {result.target.name}",
        f"Target: {result.target.display_value}",
        "",
        "Check-Host:",
        "",
        "🇷🇺 RU",
    ]
    lines.extend(_nodes(result, "ru"))
    lines.extend(["", "🌍 Control"])
    lines.extend(_nodes(result, "control"))
    lines.extend(
        [
            "",
            "CheburCheck:",
            *_chebur(result),
            "",
            "Verdict:",
            f"🔴 {result.analysis.verdict.value}",
            "",
            result.analysis.reason,
        ]
    )
    if result.checkhost.report_urls:
        lines.extend(["", "Check-Host report:", *result.checkhost.report_urls])
    return "\n".join(lines)


def recovery_message(result: TargetResult, previous: str | None) -> str:
    if not result.chebur.available:
        chebur_status = "unavailable"
    elif result.chebur.blocked:
        chebur_status = "SIGNALS"
    else:
        chebur_status = "CLEAR"
    return "\n".join(
        [
            "✅ Доступ восстановлен",
            "",
            f"Node: {result.target.name}",
            f"Target: {result.target.display_value}",
            "",
            f"🇷🇺 Russia: {result.analysis.ru_ok}/{result.analysis.ru_total} OK",
            f"🌍 Control: {result.analysis.control_ok}/{result.analysis.control_total} OK",
            f"CheburCheck: {chebur_status}",
            "",
            f"Предыдущий статус: {previous or 'UNKNOWN'}",
            f"Текущий: {result.analysis.verdict.value}",
        ]
    )
