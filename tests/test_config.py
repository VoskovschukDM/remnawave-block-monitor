import tempfile
import unittest
from pathlib import Path

from remnawave_block_monitor.config import Config, ConfigError


class ConfigTests(unittest.TestCase):
    def test_secrets_are_excluded_from_summary(self):
        config = Config(telegram_bot_token="supersecret", telegram_chat_id="123")
        summary = repr(config.safe_summary())
        self.assertNotIn("supersecret", summary)
        self.assertNotIn("telegram_chat_id", summary)

    def test_malformed_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "config.env")
            path.write_text("NOT_AN_ASSIGNMENT\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                Config.load(path)

    def test_telegram_credentials_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "config.env")
            path.write_text("TELEGRAM_ENABLED=true\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "TELEGRAM_BOT_TOKEN"):
                Config.load(path)

    def test_telegram_message_thread_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "config.env")
            path.write_text("TELEGRAM_MESSAGE_THREAD_ID=123\n", encoding="utf-8")
            self.assertEqual(Config.load(path).telegram_message_thread_id, 123)

    def test_telegram_message_thread_id_must_be_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "config.env")
            path.write_text("TELEGRAM_MESSAGE_THREAD_ID=0\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "TELEGRAM_MESSAGE_THREAD_ID"):
                Config.load(path)


if __name__ == "__main__":
    unittest.main()

