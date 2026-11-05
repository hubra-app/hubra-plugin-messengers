"""Event handlers: what the club publishes goes to its messengers.

Messenger groups can be open to anyone, so only what the whole club may see
is posted: no event, post or poll for some groups only, and members-only
events only when the club switched that on.
"""

from __future__ import annotations

from hubra.core.extensions import db

from . import messages, services


def _event_ok(event) -> bool:
    if event is None or event.group_id is not None:
        return False
    return bool(event.is_public) or bool(services.config().get("members_only_events"))


def _poll_ok(poll) -> bool:
    return (
        poll is not None
        and poll.group_id is None
        and not poll.required_group_ids
        and not poll.required_function_ids
    )


def _event(event_id):
    from hubra.core.models.event import ClubEvent

    return db.session.get(ClubEvent, event_id) if event_id else None


def _poll(poll_id):
    from hubra.core.models.poll import Poll

    return db.session.get(Poll, poll_id) if poll_id else None


def on_event_published(tenant_id=None, event_id=None, **_):
    event = _event(event_id)
    if _event_ok(event):
        services.announce("event", messages.event_message(event), f"event:{event.id}")


def on_event_reminder(tenant_id=None, event_id=None, **_):
    event = _event(event_id)
    if _event_ok(event):
        services.announce(
            "reminder",
            messages.event_message(event, reminder=True),
            f"event:{event.id}",
        )


def on_post_published(tenant_id=None, post_id=None, **_):
    from hubra.core.models.post import Post

    post = db.session.get(Post, post_id) if post_id else None
    if post is not None and post.group_id is None:
        services.announce("post", messages.post_message(post), f"post:{post.id}")


def on_poll_published(tenant_id=None, poll_id=None, **_):
    poll = _poll(poll_id)
    if _poll_ok(poll):
        services.announce("poll", messages.poll_message(poll), f"poll:{poll.id}")


def on_poll_closing(tenant_id=None, poll_id=None, **_):
    poll = _poll(poll_id)
    if _poll_ok(poll):
        services.announce(
            "reminder", messages.poll_message(poll, closing=True), f"poll:{poll.id}"
        )
