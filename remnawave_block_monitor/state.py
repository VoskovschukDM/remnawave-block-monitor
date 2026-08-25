from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import ALERTABLE_VERDICTS, Verdict


@dataclass
class Transition:
    action: str | None
    previous_notified_verdict: str | None
    bad_streak: int
    good_streak: int


class StateStore:
    VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, object] = {"version": self.VERSION, "targets": {}}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("version") != self.VERSION or not isinstance(loaded.get("targets"), dict):
                raise ValueError("unsupported state format")
            self.data = loaded
        except (OSError, ValueError, json.JSONDecodeError):
            # A corrupt state must not prevent monitoring. Preserve it for diagnosis.
            corrupt = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                os.replace(self.path, corrupt)
            except OSError:
                pass
            self.data = {"version": self.VERSION, "targets": {}}

    def apply(
        self,
        key: str,
        verdict: Verdict,
        failures: int,
        recoveries: int,
        notifications_enabled: bool = True,
    ) -> Transition:
        targets = self.data.setdefault("targets", {})
        assert isinstance(targets, dict)
        entry = targets.get(key)
        if not isinstance(entry, dict):
            entry = {
                "last_verdict": None,
                "bad_streak": 0,
                "good_streak": 0,
                "notified": False,
                "notified_verdict": None,
            }
            targets[key] = entry
        try:
            bad_streak = max(0, int(entry.get("bad_streak", 0)))
        except (TypeError, ValueError):
            bad_streak = 0
        try:
            good_streak = max(0, int(entry.get("good_streak", 0)))
        except (TypeError, ValueError):
            good_streak = 0
        entry["bad_streak"] = bad_streak
        entry["good_streak"] = good_streak
        entry["notified"] = entry.get("notified") is True
        previous_notified = entry.get("notified_verdict")
        action: str | None = None

        if verdict in ALERTABLE_VERDICTS:
            entry["bad_streak"] = bad_streak + 1
            entry["good_streak"] = 0
            if notifications_enabled and not entry.get("notified") and entry["bad_streak"] >= failures:
                entry["notified"] = True
                entry["notified_verdict"] = verdict.value
                action = "alert"
            elif entry.get("notified") and entry.get("notified_verdict") != verdict.value:
                entry["notified_verdict"] = verdict.value
                action = "alert"
        elif verdict == Verdict.OK:
            entry["bad_streak"] = 0
            entry["good_streak"] = good_streak + 1
            if entry.get("notified") and entry["good_streak"] >= recoveries:
                action = "recovery"
                entry["notified"] = False
                entry["notified_verdict"] = None
        else:
            # A non-alertable sample breaks both consecutive-sample streaks.
            entry["bad_streak"] = 0
            entry["good_streak"] = 0

        entry["last_verdict"] = verdict.value
        self.save()
        return Transition(
            action,
            previous_notified if isinstance(previous_notified, str) else None,
            int(entry["bad_streak"]),
            int(entry["good_streak"]),
        )

    def notification_failed(self, key: str, transition: Transition) -> None:
        targets = self.data.get("targets", {})
        if not isinstance(targets, dict) or not isinstance(targets.get(key), dict):
            return
        entry = targets[key]
        assert isinstance(entry, dict)
        if transition.action == "alert":
            entry["notified"] = transition.previous_notified_verdict is not None
            entry["notified_verdict"] = transition.previous_notified_verdict
        elif transition.action == "recovery":
            entry["notified"] = True
            entry["notified_verdict"] = transition.previous_notified_verdict
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            if hasattr(os, "O_DIRECTORY"):
                directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
