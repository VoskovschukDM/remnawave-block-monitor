import tempfile
import unittest
from pathlib import Path

from remnawave_block_monitor.targets import FileTargetProvider, TargetParseError, parse_target_line


class TargetTests(unittest.TestCase):
    def test_ip_defaults_to_tcp(self):
        target = parse_target_line("Server | 1.2.3.4 | auto", 443, ("tcp", "http"))
        self.assertEqual(target.modes, ("tcp",))
        self.assertEqual(target.port, 443)

    def test_domain_uses_configured_modes(self):
        target = parse_target_line("Node | node.example.com:8443", 443, ("tcp", "http"))
        self.assertEqual(target.modes, ("tcp", "http"))
        self.assertEqual(target.url, "https://node.example.com:8443")

    def test_url_is_http(self):
        target = parse_target_line("Panel | https://panel.example.com/path | http", 443, ("tcp", "http"))
        self.assertEqual(target.modes, ("http",))
        self.assertEqual(target.chebur_value, "panel.example.com")

    def test_port_80_domain_uses_http_scheme(self):
        target = parse_target_line("Web | example.com:80", 443, ("tcp", "http"))
        self.assertEqual(target.url, "http://example.com:80")

    def test_url_query_is_redacted_for_display(self):
        target = parse_target_line("https://example.com/sub/token?key=supersecret", 443, ("http",))
        self.assertEqual(target.name, "example.com")
        self.assertNotIn("supersecret", target.display_value)
        self.assertIn("redacted", target.display_value)

    def test_url_userinfo_is_rejected(self):
        with self.assertRaises(TargetParseError):
            parse_target_line("https://user:password@example.com", 443, ("http",))

    def test_ipv6(self):
        target = parse_target_line("IPv6 | [2001:db8::1]:443 | tcp", 80, ("tcp",))
        self.assertEqual(target.host, "2001:db8::1")
        self.assertEqual(target.port, 443)

    def test_invalid_type(self):
        with self.assertRaises(TargetParseError):
            parse_target_line("Bad | example.com | ping", 443, ("tcp",))

    def test_empty_and_malformed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "targets.txt")
            path.write_text("# comment\n\nBad | too | many | fields\n", encoding="utf-8")
            with self.assertLogs("remnawave_block_monitor.targets", "WARNING"):
                targets = FileTargetProvider(path, 443, ("tcp",)).get_targets()
            self.assertEqual(targets, [])


if __name__ == "__main__":
    unittest.main()
