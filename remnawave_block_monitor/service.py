from __future__ import annotations

import logging
import random
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

from .analyzer import analyze
from .checkhost import CheckHostClient
from .cheburcheck import CheburCheckClient
from .config import Config
from .http_client import ExternalServiceError
from .models import CheckHostResult, CheburResult, Target, TargetResult
from .notifier import TelegramNotifier, alert_message, recovery_message
from .state import StateStore
from .targets import TargetProvider

LOG = logging.getLogger(__name__)


class MonitorService:
    def __init__(self, config: Config, provider: TargetProvider):
        self.config = config
        self.provider = provider
        self.checkhost = CheckHostClient(config)
        self.chebur = CheburCheckClient(config)
        self.notifier = TelegramNotifier(config)
        self.state = StateStore(config.state_file)
        self.state.load()

    def check_target(self, target: Target) -> TargetResult:
        LOG.info("Checking %s %s", target.name, target.display_value)
        try:
            checkhost = self.checkhost.check(target)
        except Exception as exc:  # Target isolation is intentional at this service boundary.
            LOG.exception("Unexpected Check-Host failure for %s", target.name)
            checkhost = CheckHostResult(False, errors=[f"internal error: {type(exc).__name__}"])
        try:
            chebur = self.chebur.check(target)
        except Exception as exc:
            LOG.exception("Unexpected CheburCheck failure for %s", target.name)
            chebur = CheburResult(False, error=f"internal error: {type(exc).__name__}")
        analysis = analyze(checkhost, chebur)
        return TargetResult(target, checkhost, chebur, analysis)

    def run_cycle(self) -> list[TargetResult]:
        targets = self.provider.get_targets()
        if not targets:
            LOG.warning("No valid targets configured; cycle completed without checks")
            return []
        results: list[TargetResult] = []
        with ThreadPoolExecutor(max_workers=self.config.max_concurrent_targets, thread_name_prefix="target") as executor:
            futures: dict[Future[TargetResult], Target] = {
                executor.submit(self.check_target, target): target for target in targets
            }
            for future in as_completed(futures):
                target = futures[future]
                try:
                    result = future.result()
                except Exception:
                    LOG.exception("Unhandled target failure for %s", target.name)
                    continue
                results.append(result)
                self._record(result)
        return results

    def _record(self, result: TargetResult) -> None:
        analysis = result.analysis
        LOG.info(
            "Check-Host: RU %d/%d OK, control %d/%d OK",
            analysis.ru_ok,
            analysis.ru_total,
            analysis.control_ok,
            analysis.control_total,
        )
        if result.chebur.available:
            LOG.info("CheburCheck: blocked=%s", str(result.chebur.blocked).lower())
        else:
            LOG.warning(
                "CheburCheck unavailable for %s: %s",
                result.target.name,
                result.chebur.error or "no data",
            )
        for error in result.checkhost.errors:
            LOG.warning("%s", error)
        LOG.info("Verdict for %s: %s", result.target.name, analysis.verdict.value)

        transition = self.state.apply(
            result.target.key,
            analysis.verdict,
            self.config.failures_before_alert,
            self.config.recoveries_before_alert,
            notifications_enabled=self.notifier.enabled,
        )
        if not transition.action:
            return
        try:
            if transition.action == "alert":
                LOG.warning("Alert threshold reached for %s: %s", result.target.name, analysis.verdict.value)
                self.notifier.send(alert_message(result))
            else:
                LOG.warning("Recovery threshold reached for %s", result.target.name)
                self.notifier.send(recovery_message(result, transition.previous_notified_verdict))
        except ExternalServiceError as exc:
            self.state.notification_failed(result.target.key, transition)
            LOG.error("Notification delivery failed: %s", exc)
        except Exception as exc:
            self.state.notification_failed(result.target.key, transition)
            LOG.error("Unexpected notification failure: %s", type(exc).__name__)

    def run_forever(self) -> None:
        while True:
            started = time.monotonic()
            try:
                self.run_cycle()
            except (OSError, ValueError) as exc:
                LOG.error("Monitoring cycle failed: %s", exc)
            elapsed = time.monotonic() - started
            jitter = random.uniform(0, self.config.check_jitter_seconds) if self.config.check_jitter_seconds else 0
            delay = self.config.check_interval_seconds + jitter
            LOG.info("Cycle completed in %.1f s; next cycle in %.1f s", elapsed, delay)
            time.sleep(delay)
