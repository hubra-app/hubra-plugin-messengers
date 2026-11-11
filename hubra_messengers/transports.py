"""Sending one message to Telegram, Signal or Matrix.

Telegram: the Bot API (sendMessage). Signal has no bot API; the club runs
signal-cli-rest-api (github.com/bbernhard/signal-cli-rest-api) with a
registered number and Hubra calls its /v2/send. Matrix: the client-server
API with an access token (PUT …/rooms/<room>/send/m.room.message/<txn>).

Signal and Matrix addresses come from the club, so they are checked before
every call: https only, no redirects, and the host must resolve to public
addresses. The connection then goes to the address that was checked, so a
name that resolves differently a moment later (DNS rebinding) can't steer
it into a private network. A platform can allow private hosts by name (a
signal-cli container next to Hubra) with MESSENGERS_PRIVATE_HOSTS.

No error says more than the HTTP status and the server's own short reason:
the Telegram token is part of the address and the others are headers, so
messages from http.client must never reach the board or the logs.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.parse
import uuid

from .messages import Message

TIMEOUT = 20
CHANNELS = ("telegram", "signal", "matrix")


class SendError(Exception):
    """Shown to the board, so it never carries a token."""


MAX_BODY = 1 << 20  # what is read of a reply; ours are a few hundred bytes
USER_AGENT = "Hubra-Messengers/1"
_TELEGRAM_TOKEN = re.compile(r"^[0-9]+:[A-Za-z0-9_-]+$")


class _Pinned(http.client.HTTPSConnection):
    """Connects to an address checked beforehand, with SNI and the
    certificate check for the host name."""

    def __init__(self, host: str, ip: str, port: int):
        super().__init__(
            host, port, timeout=TIMEOUT, context=ssl.create_default_context()
        )
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _connection(url: str) -> tuple[http.client.HTTPConnection, str]:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        raise SendError("the address is missing")
    try:
        port = parts.port
    except ValueError:
        raise SendError("the address's port is not valid") from None
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    if host in _private_ok():
        if parts.scheme == "http":
            return http.client.HTTPConnection(host, port, timeout=TIMEOUT), path
        if parts.scheme != "https":
            raise SendError("the address must start with https://")
        return http.client.HTTPSConnection(host, port, timeout=TIMEOUT), path
    if parts.scheme != "https":
        raise SendError("the address must start with https://")
    port = port or 443
    return _Pinned(host, _public_ips(host, port)[0], port), path


def _reason(raw: bytes) -> str:
    try:
        got = json.loads(raw or b"{}")
        return str(
            got.get("description") or got.get("error") or got.get("errcode") or ""
        )[:200]
    except (ValueError, AttributeError):
        return ""


def _request(method: str, url: str, body: dict, headers: dict | None = None) -> dict:
    """One JSON call; tests replace this. Follows no redirect."""
    data = json.dumps(body).encode()
    try:
        conn, path = _connection(url)
        try:
            conn.request(
                method,
                path,
                body=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                    **(headers or {}),
                },
            )
            resp = conn.getresponse()
            status, raw = resp.status, resp.read(MAX_BODY)
        finally:
            conn.close()
    except SendError:
        raise
    except (OSError, TimeoutError):  # incl. ssl and socket errors
        raise SendError("the server can't be reached") from None
    except (ValueError, http.client.HTTPException):
        # e.g. a token with a space or a line break; the message holds it
        raise SendError("the request couldn't be sent; check the settings") from None
    if status >= 300:
        detail = _reason(raw)
        raise SendError(f"HTTP {int(status)}" + (f": {detail}" if detail else ""))
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def _private_ok() -> set[str]:
    return {
        h.strip().lower()
        for h in os.environ.get("MESSENGERS_PRIVATE_HOSTS", "").split(",")
        if h.strip()
    }


def check_url(raw: str) -> str:
    """The club's server address, or SendError when Hubra mustn't call it."""
    url = (raw or "").strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        raise SendError("the address is missing")
    if host in _private_ok():
        if parts.scheme not in ("https", "http"):
            raise SendError("the address must start with https://")
        return url
    if parts.scheme != "https":
        raise SendError("the address must start with https://")
    if parts.username or parts.password:
        raise SendError("the address must not contain a user name or password")
    if any(c.isspace() for c in url):
        raise SendError("the address must not contain spaces")
    try:
        port = parts.port or 443
    except ValueError:
        raise SendError("the address's port is not valid") from None
    _public_ips(host, port)
    return url


def _public_ips(host: str, port: int) -> list[str]:
    """The host's addresses, or SendError when one of them isn't public."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        raise SendError("the address's host is unknown") from None
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise SendError("the address points into a private network")
        ips.append(str(ip))
    if not ips:
        raise SendError("the address's host is unknown")
    return ips


def _token(cfg: dict, key: str) -> str:
    """A token as it goes into a header: no spaces or line breaks."""
    value = str(cfg.get(key) or "").strip()
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise SendError("the token doesn't look right")
    return value


def telegram(cfg: dict, msg: Message) -> str:
    token, chat = (
        str(cfg.get("telegram_token") or "").strip(),
        str(cfg.get("telegram_chat") or "").strip(),
    )
    if not _TELEGRAM_TOKEN.match(token):
        raise SendError("the bot token doesn't look right")
    got = _request(
        "POST",
        f"https://api.telegram.org/bot{token}/sendMessage",
        {
            "chat_id": chat,
            "text": msg.html()[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )
    if not got.get("ok", True):
        raise SendError(
            str(got.get("description") or "Telegram refused the message")[:200]
        )
    return str((got.get("result") or {}).get("message_id") or "")


def signal(cfg: dict, msg: Message) -> str:
    base = check_url(str(cfg.get("signal_url") or ""))
    headers = {}
    if token := _token(cfg, "signal_token"):
        headers["Authorization"] = f"Bearer {token}"
    got = _request(
        "POST",
        f"{base}/v2/send",
        {
            "message": msg.plain()[:4000],
            "number": str(cfg.get("signal_number") or "").strip(),
            "recipients": [str(cfg.get("signal_group") or "").strip()],
        },
        headers,
    )
    return str(got.get("timestamp") or "")


def matrix(cfg: dict, msg: Message) -> str:
    base = check_url(str(cfg.get("matrix_homeserver") or ""))
    room = urllib.parse.quote(str(cfg.get("matrix_room") or "").strip(), safe="")
    txn = uuid.uuid4().hex
    got = _request(
        "PUT",
        f"{base}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}",
        {
            "msgtype": "m.text",
            "body": msg.plain(),
            "format": "org.matrix.custom.html",
            "formatted_body": msg.html().replace("\n", "<br>"),
        },
        {"Authorization": f"Bearer {_token(cfg, 'matrix_token')}"},
    )
    return str(got.get("event_id") or "")


SENDERS = {"telegram": telegram, "signal": signal, "matrix": matrix}

# What each messenger needs before it counts as set up.
NEEDS = {
    "telegram": ("telegram_token", "telegram_chat"),
    "signal": ("signal_url", "signal_number", "signal_group"),
    "matrix": ("matrix_homeserver", "matrix_token", "matrix_room"),
}


def configured(cfg: dict) -> list[str]:
    return [c for c in CHANNELS if all(str(cfg.get(k) or "").strip() for k in NEEDS[c])]
