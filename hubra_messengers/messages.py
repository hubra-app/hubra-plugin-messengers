"""What is posted: one message per event, post, poll or reminder.

A message is a title, a few short lines (when, where, until when), an
optional text and a link into the club app. Each messenger gets it in the
form it shows best: HTML for Telegram and Matrix, plain text for Signal.
Texts are German like the rest of the club's announcements.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

TEXT_LIMIT = 600


@dataclass
class Message:
    title: str
    lines: list[str] = field(default_factory=list)
    text: str = ""
    url: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Message:
        data = json.loads(raw)
        return cls(
            title=str(data.get("title") or ""),
            lines=[str(x) for x in data.get("lines") or []],
            text=str(data.get("text") or ""),
            url=data.get("url"),
        )

    def plain(self) -> str:
        parts = [self.title, *self.lines]
        if self.text:
            parts += ["", self.text]
        if self.url:
            parts += ["", self.url]
        return "\n".join(parts)

    def html(self) -> str:
        """The small HTML both Telegram and Matrix understand."""
        parts = [
            f"<b>{html.escape(self.title)}</b>",
            *(html.escape(x) for x in self.lines),
        ]
        if self.text:
            parts += ["", html.escape(self.text)]
        if self.url:
            parts += [
                "",
                f'<a href="{html.escape(self.url, quote=True)}">In Hubra öffnen</a>',
            ]
        return "\n".join(parts)


def clip(text: str | None, limit: int = TEXT_LIMIT) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def club_url(path: str) -> str | None:
    """A link into the club app with the club in it (/<club>/app/…)."""
    from hubra.core.services.email import _get_base_url
    from hubra.core.tenant.context import current_tenant

    base = _get_base_url()
    if not base:
        return None
    tenant = current_tenant()
    prefix = f"/{tenant.slug}" if tenant is not None else ""
    return f"{base.rstrip('/')}{prefix}{path}"


def _local(at: datetime) -> datetime:
    from zoneinfo import ZoneInfo

    from flask import current_app

    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(current_app.config.get("MAIL_TIMEZONE") or "Europe/Zurich")
    except Exception:  # noqa: BLE001 - a bad setting falls back to Zurich
        zone = ZoneInfo("Europe/Zurich")
    return at.astimezone(zone)


def when(event) -> str:
    text = f"{event.date:%d.%m.%Y}"
    if event.end_date and event.end_date != event.date:
        text += f" – {event.end_date:%d.%m.%Y}"
    if event.time and not event.all_day:
        text += f", {event.time} Uhr"
    return text


def event_message(event, reminder: bool = False) -> Message:
    lines = [f"🗓️ {when(event)}"]
    if event.location:
        lines.append(f"📍 {event.location}")
    if event.meeting_url:
        lines.append(f"🔗 {event.meeting_url}")
    deadline = getattr(event, "registration_deadline", None)
    if deadline and not reminder:
        lines.append(f"⏳ Anmeldung bis {_local(deadline):%d.%m.%Y, %H:%M} Uhr")
    title = f"⏰ Erinnerung: {event.title}" if reminder else f"📅 {event.title}"
    return Message(
        clip(title, 250),
        lines,
        "" if reminder else clip(event.description),
        club_url(f"/app/operations/events?event={event.id}"),
    )


def post_message(post) -> Message:
    return Message(
        clip(f"📰 {post.title}", 250),
        [],
        clip(post.summary or post.body),
        club_url(f"/app/operations/posts/{post.id}"),
    )


def poll_message(poll, closing: bool = False) -> Message:
    lines = []
    if not closing:
        lines = [f"• {o.label}" for o in sorted(poll.options, key=lambda o: o.id)][:10]
    if poll.closes_at:
        lines.append(f"⏳ Abstimmen bis {_local(poll.closes_at):%d.%m.%Y, %H:%M} Uhr")
    title = (
        f"⏰ Umfrage schliesst bald: {poll.question}"
        if closing
        else f"📊 {poll.question}"
    )
    return Message(
        clip(title, 250), lines, "", club_url(f"/app/operations/polls?poll={poll.id}")
    )
