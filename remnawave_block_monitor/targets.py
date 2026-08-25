from __future__ import annotations

import ipaddress
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlsplit

from .models import Target

LOG = logging.getLogger(__name__)
HOST_PORT_RE = re.compile(r"^\[([^]]+)](?::(\d+))?$|^([^:]+)(?::(\d+))?$")


class TargetParseError(ValueError):
    pass


class TargetProvider(ABC):
    @abstractmethod
    def get_targets(self) -> list[Target]:
        raise NotImplementedError


class FileTargetProvider(TargetProvider):
    def __init__(self, path: str | Path, default_port: int, domain_modes: tuple[str, ...]):
        self.path = Path(path)
        self.default_port = default_port
        self.domain_modes = domain_modes

    def get_targets(self) -> list[Target]:
        if not self.path.exists():
            raise FileNotFoundError(f"Targets file not found: {self.path}")
        targets: list[Target] = []
        for number, raw in enumerate(self.path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                targets.append(parse_target_line(line, self.default_port, self.domain_modes))
            except TargetParseError as exc:
                LOG.warning("Ignoring malformed target line %d: %s", number, exc)
        return targets


class RemnawaveTargetProvider(TargetProvider):
    """Extension point for a future, specification-backed Remnawave API client."""

    def get_targets(self) -> list[Target]:
        raise NotImplementedError("Remnawave API provider is not implemented")


def _split_host_port(value: str, default_port: int) -> tuple[str, int]:
    match = HOST_PORT_RE.fullmatch(value.strip())
    if not match:
        raise TargetParseError("invalid host or host:port")
    host = match.group(1) or match.group(3) or ""
    port_text = match.group(2) or match.group(4)
    port = int(port_text) if port_text else default_port
    if not host or not 1 <= port <= 65535:
        raise TargetParseError("port must be between 1 and 65535")
    if any(char.isspace() for char in host):
        raise TargetParseError("host contains whitespace")
    return host, port


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def parse_target_line(line: str, default_port: int, domain_modes: tuple[str, ...]) -> Target:
    parts = [part.strip() for part in line.split("|")]
    implicit_name = len(parts) == 1
    if len(parts) == 1:
        name, value, explicit_kind = parts[0], parts[0], ""
    elif len(parts) in {2, 3}:
        name, value = parts[0], parts[1]
        explicit_kind = parts[2].lower() if len(parts) == 3 else ""
    else:
        raise TargetParseError("expected 'target' or 'name | target | type'")
    if not name or not value:
        raise TargetParseError("name and target must not be empty")
    if explicit_kind and explicit_kind not in {"tcp", "http", "https", "auto"}:
        raise TargetParseError("type must be tcp, http, https, auto, or omitted")

    is_url = value.lower().startswith(("http://", "https://"))
    if is_url:
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.scheme not in {"http", "https"}:
            raise TargetParseError("invalid HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise TargetParseError("URL userinfo is not supported")
        if implicit_name:
            name = parsed.hostname
        try:
            port = parsed.port
        except ValueError as exc:
            raise TargetParseError("invalid URL port") from exc
        if explicit_kind == "tcp":
            tcp_port = port or (443 if parsed.scheme == "https" else 80)
            return Target(name, value, "tcp", parsed.hostname, tcp_port, value, ("tcp",))
        return Target(name, value, "http", parsed.hostname, port, value, ("http",))

    host, port = _split_host_port(value, default_port)
    if any(character in host for character in "/?#@"):
        raise TargetParseError("bare host contains URL delimiters; use a full HTTP(S) URL")
    if explicit_kind in {"http", "https"}:
        scheme = "https" if explicit_kind == "https" or port == 443 else "http"
        url = f"{scheme}://{host}:{port}"
        return Target(name, value, "http", host, port, url, ("http",))
    modes = ("tcp",) if _is_ip(host) or explicit_kind == "tcp" else domain_modes
    scheme = "http" if port == 80 else "https"
    url = f"{scheme}://{host}:{port}" if "http" in modes else None
    return Target(name, value, "tcp", host, port, url, modes)
