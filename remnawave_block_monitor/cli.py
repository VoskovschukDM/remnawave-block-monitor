from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

from . import __version__
from .config import Config, ConfigError
from .http_client import ExternalServiceError
from .notifier import TelegramNotifier
from .service import MonitorService
from .targets import FileTargetProvider, TargetProvider, parse_target_line


class SingleTargetProvider(TargetProvider):
    def __init__(self, target):
        self.target = target

    def get_targets(self):
        return [self.target]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="remnawave-block-monitor")
    result.add_argument("--config", default="/etc/remnawave-block-monitor/config.env", help="path to config.env")
    result.add_argument("--targets-file", help="override targets file")
    result.add_argument("--state-file", help="override state file")
    result.add_argument("--once", action="store_true", help="run one complete cycle and exit")
    result.add_argument("--target", help="check a single target instead of targets.txt")
    result.add_argument("--test-telegram", action="store_true", help="send one Telegram test message and exit")
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return result


def configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level), format="[%(levelname)s] %(message)s", stream=sys.stdout)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = Config.load(args.config)
        if args.targets_file or args.state_file:
            config = replace(
                config,
                targets_file=args.targets_file or config.targets_file,
                state_file=args.state_file or config.state_file,
            )
        configure_logging(config.log_level)
        if args.test_telegram:
            if not config.telegram_enabled:
                raise ConfigError("TELEGRAM_ENABLED must be true for --test-telegram")
            TelegramNotifier(config).test()
            logging.info("Telegram test message sent")
            return 0
        if args.target:
            provider: TargetProvider = SingleTargetProvider(
                parse_target_line(args.target, config.default_port, config.domain_check_mode)
            )
        else:
            provider = FileTargetProvider(config.targets_file, config.default_port, config.domain_check_mode)
        service = MonitorService(config, provider)
        if args.once or args.target:
            service.run_cycle()
        else:
            service.run_forever()
        return 0
    except KeyboardInterrupt:
        logging.info("Stopped")
        return 130
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except ExternalServiceError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"[ERROR] Local I/O error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
