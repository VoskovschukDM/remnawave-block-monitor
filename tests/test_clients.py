import io
import unittest
from email.message import Message
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from remnawave_block_monitor.checkhost import CheckHostClient
from remnawave_block_monitor.cheburcheck import CheburCheckClient
from remnawave_block_monitor.config import Config
from remnawave_block_monitor.http_client import ExternalServiceError, JsonHttpClient
from remnawave_block_monitor.models import Target
from remnawave_block_monitor.notifier import TelegramNotifier


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _size=-1):
        return self.payload


class ClientTests(unittest.TestCase):
    def test_http_429_honors_retry_after(self):
        headers = Message()
        headers["Retry-After"] = "2"
        error = HTTPError("https://service.invalid", 429, "rate", headers, io.BytesIO())
        with patch("remnawave_block_monitor.http_client.urlopen", side_effect=[error, FakeResponse(b'{"ok": true}')]), patch(
            "remnawave_block_monitor.http_client.time.sleep"
        ) as sleeper:
            payload = JsonHttpClient("Test", attempts=2).request("https://service.invalid", 1)
        self.assertTrue(payload["ok"])
        sleeper.assert_called_once_with(2.0)

    def test_dns_error_is_sanitized(self):
        with patch("remnawave_block_monitor.http_client.urlopen", side_effect=URLError("secret-hostname")):
            with self.assertRaisesRegex(ExternalServiceError, "network, DNS, or timeout error") as caught:
                JsonHttpClient("Test", attempts=1).request("https://token@example.invalid", 1)
        self.assertNotIn("token", str(caught.exception))
        self.assertNotIn("secret-hostname", str(caught.exception))

    def test_invalid_json(self):
        with patch("remnawave_block_monitor.http_client.urlopen", return_value=FakeResponse(b"nope")):
            with self.assertRaisesRegex(ExternalServiceError, "invalid JSON"):
                JsonHttpClient("Test", attempts=1).request("https://service.invalid", 1)

    def test_checkhost_node_round_robin(self):
        nodes = {
            "de1": {"location": ["de", "Germany", "A"]},
            "de2": {"location": ["de", "Germany", "B"]},
            "nl1": {"location": ["nl", "Netherlands", "C"]},
            "fi1": {"location": ["fi", "Finland", "D"]},
        }
        self.assertEqual(CheckHostClient._select(nodes, ("DE", "NL", "FI"), 3), ["de1", "nl1", "fi1"])

    def test_tcp_and_http_parsers(self):
        client = CheckHostClient(Config())
        tcp = client._parse_node("tcp", "ru1", [{"time": 0.031, "address": "1.2.3.4"}], "ru", {"location": ["ru", "Russia", "Moscow"]})
        http = client._parse_node("http", "ru1", [[0, 0.1, "Not Found", "404", "1.2.3.4"]], "ru", {"location": ["ru", "Russia", "Moscow"]})
        self.assertTrue(tcp.success)
        self.assertTrue(http.success, "An HTTP 404 still proves HTTP-layer reachability")

    def test_chebur_response_contract(self):
        client = CheburCheckClient(Config())
        client.http.request = lambda *_args, **_kwargs: {
            "target_type": "Домен",
            "blocked": True,
            "rkn_domain": "example.org",
            "ips": ["1.2.3.4"],
            "blocked_subnets": ["1.2.0.0/16"],
            "cdn_providers": {"provider": []},
        }
        target = Target("Test", "example.org", "tcp", "example.org", 443, None, ("tcp",))
        result = client.check(target)
        self.assertTrue(result.available)
        self.assertTrue(result.blocked)
        self.assertEqual(result.blocked_subnets, ["1.2.0.0/16"])

    def test_telegram_sends_to_configured_topic(self):
        notifier = TelegramNotifier(
            Config(
                telegram_enabled=True,
                telegram_bot_token="token",
                telegram_chat_id="-100123",
                telegram_message_thread_id=456,
            )
        )
        request = Mock(return_value={"ok": True})
        notifier.http.request = request

        notifier.send("test")

        form = parse_qs(request.call_args.kwargs["data"].decode())
        self.assertEqual(form["chat_id"], ["-100123"])
        self.assertEqual(form["message_thread_id"], ["456"])

    def test_telegram_omits_topic_for_general(self):
        notifier = TelegramNotifier(
            Config(telegram_enabled=True, telegram_bot_token="token", telegram_chat_id="-100123")
        )
        request = Mock(return_value={"ok": True})
        notifier.http.request = request

        notifier.send("test")

        form = parse_qs(request.call_args.kwargs["data"].decode())
        self.assertNotIn("message_thread_id", form)


if __name__ == "__main__":
    unittest.main()
