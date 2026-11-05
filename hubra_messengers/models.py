"""The Messengers table (one copy per club schema)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from hubra.core.extensions import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MessengersLog(db.Model):
    """One message to one messenger: what, and whether it got there."""

    __tablename__ = "messengers_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # telegram, signal, matrix
    kind: Mapped[str] = mapped_column(
        String(12), nullable=False
    )  # event, post, poll, reminder, test
    ref: Mapped[str | None] = mapped_column(String(40))  # event:12, poll:3 …
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)  # the message as JSON
    status: Mapped[str] = mapped_column(
        String(8), default="queued", nullable=False
    )  # queued, sent, failed
    error: Mapped[str | None] = mapped_column(String(300))
    tries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
