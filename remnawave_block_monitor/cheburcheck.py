from __future__ import annotations

from urllib.parse import urlencode

from .config import Config
from .http_client import ExternalServiceError, JsonHttpClient, RateLimiter
from .models import CheburResult, Target


class CheburCheckClient:
    def __init__(self, config: Config):
        self.config = config
        self.http = JsonHttpClient(
            "CheburCheck",
            config.http_retry_attempts,
            RateLimiter(config.cheburcheck_request_delay),
        )

    def check(self, target: Target) -> CheburResult:
        if not self.config.cheburcheck_enabled:
            return CheburResult(False, error="disabled")
        query = urlencode({"target": target.chebur_value})
        try:
            payload = self.http.request(
                f"{self.config.cheburcheck_base_url}/check?{query}",
                self.config.cheburcheck_timeout,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("blocked"), bool):
                raise ExternalServiceError("CheburCheck: invalid response schema")
            subnet_values = payload.get("blocked_subnets")
            ip_values = payload.get("ips")
            return CheburResult(
                available=True,
                blocked=payload["blocked"],
                target_type=str(payload["target_type"]) if payload.get("target_type") is not None else None,
                rkn_domain=str(payload["rkn_domain"]) if payload.get("rkn_domain") is not None else None,
                blocked_subnets=(
                    [str(item) for item in subnet_values if isinstance(item, str)]
                    if isinstance(subnet_values, list)
                    else []
                ),
                ips=(
                    [str(item) for item in ip_values if isinstance(item, str)]
                    if isinstance(ip_values, list)
                    else []
                ),
                cdn_providers=(
                    payload.get("cdn_providers", {})
                    if isinstance(payload.get("cdn_providers", {}), dict)
                    else {}
                ),
            )
        except ExternalServiceError as exc:
            return CheburResult(False, error=str(exc))
