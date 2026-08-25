from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class Verdict(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    LIKELY_RU_BLOCK = "LIKELY_RU_BLOCK"
    CONFIRMED_BY_MULTIPLE_SIGNALS = "CONFIRMED_BY_MULTIPLE_SIGNALS"
    GLOBAL_DOWN = "GLOBAL_DOWN"
    CHECK_ERROR = "CHECK_ERROR"
    UNKNOWN = "UNKNOWN"


ALERTABLE_VERDICTS = {
    Verdict.LIKELY_RU_BLOCK,
    Verdict.CONFIRMED_BY_MULTIPLE_SIGNALS,
    Verdict.GLOBAL_DOWN,
}


@dataclass(frozen=True)
class Target:
    name: str
    value: str
    kind: str
    host: str
    port: int | None
    url: str | None
    modes: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.name}|{self.value}|{','.join(self.modes)}"

    @property
    def chebur_value(self) -> str:
        return self.host

    @property
    def display_value(self) -> str:
        """Target safe for logs/messages; URL query values may contain credentials."""
        if not self.value.lower().startswith(("http://", "https://")):
            return self.value
        parsed = urlsplit(self.value)
        host = parsed.hostname or self.host
        if ":" in host:
            host = f"[{host}]"
        netloc = host
        try:
            if parsed.port is not None:
                netloc = f"{host}:{parsed.port}"
        except ValueError:
            pass
        return urlunsplit((parsed.scheme, netloc, parsed.path, "<redacted>" if parsed.query else "", ""))


@dataclass(frozen=True)
class NodeResult:
    node: str
    country_code: str
    country: str
    city: str
    group: str
    mode: str
    success: bool
    latency_ms: float | None = None
    status: str = "UNKNOWN"
    detail: str = ""


@dataclass
class CheckHostResult:
    available: bool
    nodes: list[NodeResult] = field(default_factory=list)
    report_urls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    expected_modes: tuple[str, ...] = ()

    def grouped_nodes(self, group: str) -> list[NodeResult]:
        """Collapse multiple modes: a node is healthy only if all modes succeeded."""
        by_node: dict[str, list[NodeResult]] = {}
        for item in self.nodes:
            if item.group == group:
                by_node.setdefault(item.node, []).append(item)
        collapsed: list[NodeResult] = []
        for node, items in by_node.items():
            if self.expected_modes and {item.mode for item in items} != set(self.expected_modes):
                continue
            failed = [item for item in items if not item.success]
            latency_values = [item.latency_ms for item in items if item.latency_ms is not None]
            sample = items[0]
            collapsed.append(
                NodeResult(
                    node=node,
                    country_code=sample.country_code,
                    country=sample.country,
                    city=sample.city,
                    group=group,
                    mode="+".join(sorted(item.mode for item in items)),
                    success=not failed,
                    latency_ms=max(latency_values) if latency_values else None,
                    status="OK" if not failed else "; ".join(item.status for item in failed),
                    detail="; ".join(item.detail for item in failed if item.detail),
                )
            )
        return collapsed


@dataclass
class CheburResult:
    available: bool
    blocked: bool | None = None
    target_type: str | None = None
    rkn_domain: str | None = None
    blocked_subnets: list[str] = field(default_factory=list)
    ips: list[str] = field(default_factory=list)
    cdn_providers: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class Analysis:
    verdict: Verdict
    reason: str
    ru_ok: int = 0
    ru_total: int = 0
    control_ok: int = 0
    control_total: int = 0


@dataclass
class TargetResult:
    target: Target
    checkhost: CheckHostResult
    chebur: CheburResult
    analysis: Analysis
