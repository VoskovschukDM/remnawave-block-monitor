from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlencode

from .config import Config
from .http_client import ExternalServiceError, JsonHttpClient, RateLimiter
from .models import CheckHostResult, NodeResult, Target

LOG = logging.getLogger(__name__)


class CheckHostClient:
    def __init__(self, config: Config):
        self.config = config
        self.http = JsonHttpClient(
            "Check-Host",
            config.http_retry_attempts,
            RateLimiter(config.checkhost_request_delay),
        )
        self._node_cache: dict[str, dict[str, Any]] = {}
        self._node_cache_time = 0.0
        self._cache_lock = threading.Lock()

    def _nodes(self) -> dict[str, dict[str, Any]]:
        with self._cache_lock:
            if self._node_cache and time.monotonic() - self._node_cache_time < 3600:
                return self._node_cache
            payload = self.http.request(
                f"{self.config.checkhost_base_url}/nodes/hosts",
                self.config.checkhost_timeout,
            )
            nodes = payload.get("nodes") if isinstance(payload, dict) else None
            if not isinstance(nodes, dict):
                raise ExternalServiceError("Check-Host: invalid nodes response")
            self._node_cache = {str(name): value for name, value in nodes.items() if isinstance(value, dict)}
            self._node_cache_time = time.monotonic()
            return self._node_cache

    @staticmethod
    def _select(nodes: dict[str, dict[str, Any]], countries: tuple[str, ...], count: int) -> list[str]:
        buckets: dict[str, list[str]] = defaultdict(list)
        order = [country.lower() for country in countries]
        for name, value in sorted(nodes.items()):
            location = value.get("location", [])
            if isinstance(location, list) and location:
                country = str(location[0]).lower()
                if country in order:
                    buckets[country].append(name)
        selected: list[str] = []
        while len(selected) < count:
            added = False
            for country in order:
                if buckets[country]:
                    selected.append(buckets[country].pop(0))
                    added = True
                    if len(selected) == count:
                        break
            if not added:
                break
        return selected

    def _selection(self) -> tuple[list[str], list[str], dict[str, dict[str, Any]]]:
        manual = bool(self.config.checkhost_ru_nodes or self.config.checkhost_control_nodes)
        nodes: dict[str, dict[str, Any]] = {}
        if not manual or not (self.config.checkhost_ru_nodes and self.config.checkhost_control_nodes):
            nodes = self._nodes()
        ru = list(self.config.checkhost_ru_nodes) or self._select(
            nodes, self.config.checkhost_ru_countries, self.config.checkhost_ru_node_count
        )
        control = list(self.config.checkhost_control_nodes) or self._select(
            nodes, self.config.checkhost_control_countries, self.config.checkhost_control_node_count
        )
        if not ru or not control:
            raise ExternalServiceError("Check-Host: no nodes matched configured countries")
        return ru, control, nodes

    def check(self, target: Target) -> CheckHostResult:
        if not self.config.checkhost_enabled:
            return CheckHostResult(False, errors=["disabled"])
        try:
            ru, control, node_info = self._selection()
        except ExternalServiceError as exc:
            return CheckHostResult(False, errors=[str(exc)])
        result = CheckHostResult(False, expected_modes=target.modes)
        groups = {name: "ru" for name in ru} | {name: "control" for name in control}
        selected = ru + [name for name in control if name not in ru]
        for mode in target.modes:
            try:
                run_nodes, report_url, errors = self._run(mode, target, selected, groups, node_info)
                result.nodes.extend(run_nodes)
                if report_url:
                    result.report_urls.append(report_url)
                result.errors.extend(errors)
            except ExternalServiceError as exc:
                result.errors.append(str(exc))
        result.available = bool(result.nodes)
        return result

    def _run(
        self,
        mode: str,
        target: Target,
        selected: list[str],
        groups: dict[str, str],
        node_info: dict[str, dict[str, Any]],
    ) -> tuple[list[NodeResult], str | None, list[str]]:
        host_value = target.url if mode == "http" else self._tcp_host(target)
        query = urlencode([("host", host_value or target.value), *[("node", node) for node in selected]])
        payload = self.http.request(
            f"{self.config.checkhost_base_url}/check-{mode}?{query}",
            self.config.checkhost_timeout,
        )
        if not isinstance(payload, dict) or payload.get("ok") != 1 or not payload.get("request_id"):
            raise ExternalServiceError(f"Check-Host: {mode} request was rejected")
        request_id = str(payload["request_id"])
        report = payload.get("permanent_link")
        response_nodes = payload.get("nodes", {})
        if isinstance(response_nodes, dict):
            for name, value in response_nodes.items():
                if isinstance(value, list) and len(value) >= 3:
                    node_info[str(name)] = {"location": value[:3]}

        deadline = time.monotonic() + self.config.checkhost_result_timeout
        completed: dict[str, Any] = {}
        while time.monotonic() < deadline:
            data = self.http.request(
                f"{self.config.checkhost_base_url}/check-result/{request_id}",
                self.config.checkhost_timeout,
            )
            if not isinstance(data, dict):
                raise ExternalServiceError("Check-Host: invalid result response")
            for node in selected:
                if data.get(node) is not None:
                    completed[node] = data[node]
            if all(node in completed for node in selected):
                break
            time.sleep(self.config.checkhost_poll_interval)

        parsed: list[NodeResult] = []
        for node, raw in completed.items():
            parsed.append(self._parse_node(mode, node, raw, groups[node], node_info.get(node, {})))
        missing = [node for node in selected if node not in completed]
        errors = [f"Check-Host: result timeout for {len(missing)} node(s) in {mode} check"] if missing else []
        return parsed, str(report) if report else None, errors

    @staticmethod
    def _tcp_host(target: Target) -> str:
        host = f"[{target.host}]" if ":" in target.host else target.host
        return f"{host}:{target.port}"

    @staticmethod
    def _location(info: dict[str, Any], node: str) -> tuple[str, str, str]:
        location = info.get("location", []) if isinstance(info, dict) else []
        if isinstance(location, list) and len(location) >= 3:
            return str(location[0]).upper(), str(location[1]), str(location[2])
        prefix = node.split(".", 1)[0].rstrip("0123456789").upper()
        return prefix, prefix or "Unknown", node

    def _parse_node(self, mode: str, node: str, raw: Any, group: str, info: dict[str, Any]) -> NodeResult:
        code, country, city = self._location(info, node)
        if mode == "tcp":
            item = raw[0] if isinstance(raw, list) and raw else raw
            if isinstance(item, dict) and isinstance(item.get("time"), (int, float)) and not item.get("error"):
                return NodeResult(node, code, country, city, group, mode, True, float(item["time"]) * 1000, "OK")
            detail = str(item.get("error", "invalid response")) if isinstance(item, dict) else "invalid response"
            return NodeResult(node, code, country, city, group, mode, False, status="FAIL", detail=detail)

        item = raw[0] if isinstance(raw, list) and raw else raw
        if isinstance(item, list) and item:
            success_flag = item[0] == 1
            latency = float(item[1]) * 1000 if len(item) > 1 and isinstance(item[1], (int, float)) else None
            status_code = str(item[3]) if len(item) > 3 and item[3] is not None else ""
            # Any real HTTP status proves application-layer reachability, including 4xx/5xx.
            responded = success_flag or (status_code.isdigit() and 100 <= int(status_code) <= 599)
            status = f"HTTP {status_code}" if status_code else ("OK" if responded else "FAIL")
            detail = str(item[2]) if len(item) > 2 and item[2] is not None else ""
            return NodeResult(node, code, country, city, group, mode, responded, latency, status, detail)
        return NodeResult(node, code, country, city, group, mode, False, status="FAIL", detail="invalid response")
