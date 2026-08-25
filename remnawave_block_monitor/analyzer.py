from __future__ import annotations

from .models import Analysis, CheckHostResult, CheburResult, Verdict


def analyze(checkhost: CheckHostResult, chebur: CheburResult) -> Analysis:
    ru = checkhost.grouped_nodes("ru") if checkhost.available else []
    control = checkhost.grouped_nodes("control") if checkhost.available else []
    ru_ok = sum(item.success for item in ru)
    control_ok = sum(item.success for item in control)
    counts = dict(ru_ok=ru_ok, ru_total=len(ru), control_ok=control_ok, control_total=len(control))

    if checkhost.available and ru and control:
        if ru_ok == len(ru) and control_ok == len(control):
            if chebur.available and chebur.blocked:
                return Analysis(
                    Verdict.WARNING,
                    "Target is reachable, but CheburCheck reports list-based signals",
                    **counts,
                )
            return Analysis(Verdict.OK, "Russian and control nodes are reachable", **counts)
        if ru_ok == 0 and control_ok == 0:
            return Analysis(Verdict.GLOBAL_DOWN, "Target is unavailable from both Russian and control nodes", **counts)
        if ru_ok == 0 and control_ok > 0:
            if chebur.available and chebur.blocked:
                return Analysis(
                    Verdict.CONFIRMED_BY_MULTIPLE_SIGNALS,
                    "Unavailable from Russian nodes while reachable abroad; CheburCheck reports restriction signals",
                    **counts,
                )
            return Analysis(
                Verdict.LIKELY_RU_BLOCK,
                "Unavailable from Russian nodes while reachable from control nodes",
                **counts,
            )
        return Analysis(Verdict.WARNING, "Partial or asymmetric node failures", **counts)

    if checkhost.available and (ru or control):
        return Analysis(
            Verdict.UNKNOWN,
            "Check-Host returned too few node groups for comparison",
            **counts,
        )
    if chebur.available:
        if chebur.blocked:
            return Analysis(Verdict.WARNING, "CheburCheck reports signals, but reachability comparison is unavailable", **counts)
        return Analysis(Verdict.UNKNOWN, "CheburCheck is clear, but reachability comparison is unavailable", **counts)
    if checkhost.errors or chebur.error:
        return Analysis(Verdict.CHECK_ERROR, "All enabled external checks failed", **counts)
    return Analysis(Verdict.UNKNOWN, "Insufficient data", **counts)
