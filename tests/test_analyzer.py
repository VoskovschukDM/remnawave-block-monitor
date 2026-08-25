import unittest

from remnawave_block_monitor.analyzer import analyze
from remnawave_block_monitor.models import CheckHostResult, CheburResult, NodeResult, Verdict


def checkhost(ru_ok: int, ru_total: int, control_ok: int, control_total: int) -> CheckHostResult:
    nodes = []
    for group, ok_count, total, code in (
        ("ru", ru_ok, ru_total, "RU"),
        ("control", control_ok, control_total, "DE"),
    ):
        for index in range(total):
            success = index < ok_count
            nodes.append(NodeResult(f"{group}{index}", code, code, f"city{index}", group, "tcp", success, status="OK" if success else "FAIL"))
    return CheckHostResult(True, nodes)


class AnalyzerScenarios(unittest.TestCase):
    def test_all_nodes_ok_and_chebur_clear(self):
        self.assertEqual(analyze(checkhost(3, 3, 3, 3), CheburResult(True, False)).verdict, Verdict.OK)

    def test_ru_down_control_ok(self):
        self.assertEqual(analyze(checkhost(0, 3, 3, 3), CheburResult(True, False)).verdict, Verdict.LIKELY_RU_BLOCK)

    def test_multiple_signals(self):
        self.assertEqual(
            analyze(checkhost(0, 3, 3, 3), CheburResult(True, True)).verdict,
            Verdict.CONFIRMED_BY_MULTIPLE_SIGNALS,
        )

    def test_global_down(self):
        self.assertEqual(analyze(checkhost(0, 3, 0, 3), CheburResult(True, False)).verdict, Verdict.GLOBAL_DOWN)

    def test_partial_ru(self):
        self.assertEqual(analyze(checkhost(2, 3, 3, 3), CheburResult(True, False)).verdict, Verdict.WARNING)

    def test_chebur_unavailable_does_not_hide_ru_block(self):
        self.assertEqual(
            analyze(checkhost(0, 3, 3, 3), CheburResult(False, error="timeout")).verdict,
            Verdict.LIKELY_RU_BLOCK,
        )

    def test_checkhost_unavailable_chebur_signal_is_warning(self):
        result = analyze(CheckHostResult(False, errors=["timeout"]), CheburResult(True, True))
        self.assertEqual(result.verdict, Verdict.WARNING)

    def test_multiple_modes_are_collapsed_per_node(self):
        result = checkhost(3, 3, 3, 3)
        for node in list(result.nodes):
            result.nodes.append(
                NodeResult(node.node, node.country_code, node.country, node.city, node.group, "http", node.node != "ru0", status="OK" if node.node != "ru0" else "FAIL")
            )
        analysis = analyze(result, CheburResult(True, False))
        self.assertEqual((analysis.ru_ok, analysis.ru_total), (2, 3))
        self.assertEqual(analysis.verdict, Verdict.WARNING)

    def test_missing_configured_mode_is_unknown_not_ok(self):
        result = checkhost(3, 3, 3, 3)
        result.expected_modes = ("tcp", "http")
        analysis = analyze(result, CheburResult(True, False))
        self.assertEqual(analysis.verdict, Verdict.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
