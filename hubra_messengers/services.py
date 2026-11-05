"""Queueing announcements and sending them, with a few retries."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from hubra.core.extensions import db

from . import transports
from .messages import Message
from .models import MessengersLog

MAX_TRIES = 3
PER_RUN = 30
SWITCHES = {
    "event": "announce_events",
    "post": "announce_posts",
    "poll": "announce_polls",
    "reminder": "announce_reminders",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def config() -> dict:
    from hubra.core.modules import get_config

    return get_config("messengers")


def deliver(row: MessengersLog, cfg: dict) -> bool:
    """One try; the row says how it went."""
    row.tries += 1
    try:
        transports.SENDERS[row.channel](cfg, Message.from_json(row.text))
    except transports.SendError as exc:
        row.error = str(exc)[:300]
        if row.tries >= MAX_TRIES:
            row.status = "failed"
        return False
    row.status, row.error, row.sent_at = "sent", None, now()
    return True


def announce(kind: str, msg: Message, ref: str | None = None) -> int:
    """Sends *msg* to every messenger the club set up, if it wants *kind*.

    Plugin event handlers run in the worker after the change is committed,
    so sending here holds up nobody. What fails stays queued for retry().
    """
    cfg = config()
    if kind in SWITCHES and not cfg.get(SWITCHES[kind]):
        return 0
    sent = 0
    for channel in transports.configured(cfg):
        if (
            ref
            and kind != "reminder"
            and db.session.scalar(
                select(MessengersLog.id)
                .where(MessengersLog.channel == channel)
                .where(MessengersLog.ref == ref)
                .where(MessengersLog.kind == kind)
                .limit(1)
            )
        ):
            continue  # announced already (an event published twice)
        row = MessengersLog(
            channel=channel,
            kind=kind,
            ref=ref,
            title=msg.title[:300],
            text=msg.to_json(),
            status="queued",
            created_at=now(),
        )
        db.session.add(row)
        db.session.flush()
        sent += deliver(row, cfg)
    return sent


def retry() -> dict:
    """Tries the queued messages again. Called every minute."""
    done = {"sent": 0, "failed": 0}
    rows = list(
        db.session.scalars(
            select(MessengersLog)
            .where(MessengersLog.status == "queued")
            .order_by(MessengersLog.id)
            .limit(PER_RUN)
        )
    )
    if not rows:
        return done
    cfg = config()
    ready = set(transports.configured(cfg))
    for row in rows:
        if row.channel not in ready:
            row.status, row.error = "failed", "no longer set up"
            done["failed"] += 1
        elif deliver(row, cfg):
            done["sent"] += 1
        elif row.status == "failed":
            done["failed"] += 1
    return done
