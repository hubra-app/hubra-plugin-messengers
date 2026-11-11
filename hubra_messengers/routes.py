"""Messengers API: /api/v1/app/messengers (all of it needs messengers.channels.update).

GET  /status            which messengers are set up and what is announced
GET  /log               the last 100 messages (?channel=telegram|signal|matrix)
POST /test              {channel}: sends a test message now
POST /log/<id>/retry    tries a failed message again
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from hubra.core.auth.helpers import get_current_member
from hubra.core.errors import api_error
from hubra.core.extensions import db
from hubra.core.permissions import permission_required
from hubra.core.utils import log_audit

from . import services, transports
from .body import Invalid, _body, _get, _iso
from .messages import Message, club_url
from .models import MessengersLog

messengers_bp = Blueprint("messengers_bp", __name__)

LABEL = "See what went to the club's messengers and send a test message"


@messengers_bp.errorhandler(Invalid)
def _invalid(exc: Invalid):
    return api_error("VALIDATION_ERROR", exc.message, 400)


def _row(r: MessengersLog) -> dict:
    return {
        "id": r.id,
        "channel": r.channel,
        "kind": r.kind,
        "title": r.title,
        "status": r.status,
        "error": r.error,
        "tries": r.tries,
        "createdAt": _iso(r.created_at),
        "sentAt": _iso(r.sent_at),
    }


def _last(channel: str, status: str):
    return db.session.scalar(
        select(MessengersLog)
        .where(MessengersLog.channel == channel)
        .where(MessengersLog.status == status)
        .order_by(MessengersLog.id.desc())
        .limit(1)
    )


@messengers_bp.get("/status")
@permission_required("channels", "update", LABEL)
def status():
    cfg = services.config()
    ready = transports.configured(cfg)
    out = []
    for channel in transports.CHANNELS:
        sent, failed = _last(channel, "sent"), _last(channel, "failed")
        out.append(
            {
                "channel": channel,
                "configured": channel in ready,
                "lastSentAt": _iso(sent.sent_at) if sent else None,
                "lastError": failed.error
                if failed and (not sent or failed.id > sent.id)
                else None,
            }
        )
    return jsonify(
        {
            "channels": out,
            "announce": {
                kind: bool(cfg.get(key)) for kind, key in services.SWITCHES.items()
            },
            "membersOnlyEvents": bool(cfg.get("members_only_events")),
        }
    )


@messengers_bp.get("/log")
@permission_required("channels", "update", LABEL)
def log():
    query = select(MessengersLog).order_by(MessengersLog.id.desc()).limit(100)
    channel = request.args.get("channel")
    if channel in transports.CHANNELS:
        query = query.where(MessengersLog.channel == channel)
    return jsonify([_row(r) for r in db.session.scalars(query)])


@messengers_bp.post("/test")
@permission_required("channels", "update", LABEL)
def test():
    member = get_current_member()
    channel = _body().get("channel")
    if channel not in transports.CHANNELS:
        raise Invalid("channel must be telegram, signal or matrix")
    cfg = services.config()
    if channel not in transports.configured(cfg):
        return api_error("NOT_SET_UP", "Fill in this messenger's settings first.", 409)
    msg = Message(
        "👋 Test aus Hubra",
        [f"Gesendet von {member.name}"],
        "Hier erscheinen neue Anlässe, Beiträge und Umfragen des Vereins.",
        club_url("/app/dashboard"),
    )
    row = MessengersLog(
        channel=channel,
        kind="test",
        title=msg.title,
        text=msg.to_json(),
        status="queued",
        created_at=services.now(),
    )
    db.session.add(row)
    db.session.flush()
    ok = services.deliver(row, cfg)
    if not ok:
        row.status = "failed"  # a test isn't tried again by itself
    log_audit(member.id, "messengers.test", "MessengersLog", row.id, channel)
    db.session.commit()
    return jsonify(_row(row))


@messengers_bp.post("/log/<int:row_id>/retry")
@permission_required("channels", "update", LABEL)
def retry(row_id: int):
    member = get_current_member()
    row, err = _get(MessengersLog, row_id)
    if err:
        return err
    if row.status != "failed":
        return api_error("NOT_FAILED", "Only a failed message can be sent again.", 409)
    cfg = services.config()
    if row.channel not in transports.configured(cfg):
        return api_error("NOT_SET_UP", "Fill in this messenger's settings first.", 409)
    row.status, row.tries = "queued", 0
    if not services.deliver(row, cfg):
        row.status = "failed"
    log_audit(member.id, "messengers.retry", "MessengersLog", row.id, row.channel)
    db.session.commit()
    return jsonify(_row(row))
