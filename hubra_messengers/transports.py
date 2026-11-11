"""Sending one message to Telegram, Signal or Matrix.

Telegram: the Bot API (sendMessage). Signal has no bot API; the club runs
signal-cli-rest-api (github.com/bbernhard/signal-cli-rest-api) with a
registered number and Hubra calls its /v2/send. Matrix: the client-server
API with an access token (PUT …/rooms/<room>/send/m.room.message/<txn>).

Signal and Matrix addresses come from the club, so they are checked before
every call: https only, no redirects, and the host must resolve to public
addresses. The connection then goes to the very address that was checked,
so a DNS answer that changes between the check and the call (DNS
rebinding) can't point Hubra into its own network. A platform can allow
private hosts by name (a signal-cli container next to Hubra) with
MESSENGERS_PRIVATE_HOSTS. An answer is read up to MAX_ANSWER bytes only.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .messages import Message

TIMEOUT = 20
# The answers are small JSON documents; more than this is not one.
MAX_ANSWER = 1024 * 1024
CHANNELS = ("telegram", "signal", "matrix")


class SendError(Exception):
    """Shown to the board, so it never carries a token."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _checked_address(host: str, port: int) -> str:
    """The address to connect to: every address *host* resolves to must be
    public, unless the platform allowed the host by name."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        raise SendError("the address's host is unknown") from None
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise SendError("the address's host is unknown")
    if (host or "").lower() not in _private_ok():
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                raise SendError("the address points into a private network")
    return addresses[0]


class _CheckedHTTPS(http.client.HTTPSConnection):
    """Connects to the address checked at connect time, with SNI and the
    certificate check for the host name."""

    def connect(self) -> None:
        address = _checked_address(self.host, self.port)
        sock = socket.create_connection((address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _CheckedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_CheckedHTTPS, req, context=ssl.create_default_context())


# No proxy from the environment: the checked address is the one connected to.
_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirect, _CheckedHTTPSHandler
)


def _request(method: str, url: str, body: dict, headers: dict | None = None) -> dict:
    """One JSON call; tests replace this."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with _opener.open(req, timeout=TIMEOUT) as resp:
            raw = resp.read(MAX_ANSWER + 1)
        if len(raw) > MAX_ANSWER:
            raise SendError("the server's answer is too large")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            got = json.loads(exc.read(MAX_ANSWER) or b"{}")
            detail = str(
                got.get("description") or got.get("error") or got.get("errcode") or ""
            )[:200]
        except (ValueError, AttributeError):
            pass
        raise SendError(
            f"HTTP {int(exc.code)}" + (f": {detail}" if detail else "")
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SendError("the server can't be reached") from None
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
    _checked_address(host, parts.port or 443)
    return url


def telegram(cfg: dict, msg: Message) -> str:
    token, chat = (
        str(cfg.get("telegram_token") or "").strip(),
        str(cfg.get("telegram_chat") or "").strip(),
    )
    if ":" not in token or "/" in token:
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
    if cfg.get("signal_token"):
        headers["Authorization"] = f"Bearer {str(cfg['signal_token']).strip()}"
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
        {"Authorization": f"Bearer {str(cfg.get('matrix_token') or '').strip()}"},
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
