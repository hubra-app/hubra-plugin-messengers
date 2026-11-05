"""Sending one message to Telegram, Signal or Matrix.

Telegram: the Bot API (sendMessage). Signal has no bot API; the club runs
signal-cli-rest-api (github.com/bbernhard/signal-cli-rest-api) with a
registered number and Hubra calls its /v2/send. Matrix: the client-server
API with an access token (PUT …/rooms/<room>/send/m.room.message/<txn>).

Signal and Matrix addresses come from the club, so they are checked before
every call: https only, no redirects, and the host must resolve to public
addresses. A platform can allow private hosts by name (a signal-cli
container next to Hubra) with MESSENGERS_PRIVATE_HOSTS.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .messages import Message

TIMEOUT = 20
CHANNELS = ("telegram", "signal", "matrix")


class SendError(Exception):
    """Shown to the board, so it never carries a token."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_opener = urllib.request.build_opener(_NoRedirect)


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
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            got = json.loads(exc.read() or b"{}")
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
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        raise SendError("the address's host is unknown") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise SendError("the address points into a private network")
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
