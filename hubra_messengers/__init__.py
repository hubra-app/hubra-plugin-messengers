"""Messengers: club announcements in Telegram, Signal and Matrix.

New events, posts and polls, and the reminders before an event or before a
poll closes, go to the club's group in each messenger it set up in the
module's settings: a Telegram bot and chat, a Signal number through a
signal-cli REST API, or a Matrix account and room. Only what the whole club
may see is posted: members-only events only when the club says its groups
are for members, and nothing meant for some groups only.

Permission:
    messengers.channels.update   see what was sent and send a test message
"""

from hubra.core.modules import Blueprint, Module, NavItem, Schedule, SettingField
from hubra.core.modules.events import (
    EVENT_PUBLISHED,
    EVENT_REMINDER,
    POLL_CLOSING,
    POLL_PUBLISHED,
    POST_PUBLISHED,
)

_HOOKS = "hubra_messengers.hooks"

module = Module(
    code="messengers",
    name="Messengers",
    description="Announcements in Telegram, Signal and Matrix",
    default_enabled=False,
    depends_on=("members",),
    blueprints=(
        Blueprint("hubra_messengers.routes", "messengers_bp", "/api/v1/app/messengers"),
    ),
    nav=(
        NavItem(
            "/app/messengers",
            "shell.nav.messengers",
            "messages",
            section="more",
            order=34,
            perms=("messengers.channels.update",),
        ),
    ),
    settings=(
        SettingField("announce_events", "bool", default=True, label="Post new events"),
        SettingField("announce_posts", "bool", default=True, label="Post new posts"),
        SettingField("announce_polls", "bool", default=True, label="Post new polls"),
        SettingField(
            "announce_reminders",
            "bool",
            default=False,
            label="Post reminders",
            description="Before an event starts and before a poll closes",
        ),
        SettingField(
            "members_only_events",
            "bool",
            default=False,
            label="Members-only events too",
            description="Only when every group below is for members only",
        ),
        SettingField(
            "telegram_token",
            "secret",
            label="Telegram bot token",
            description="From @BotFather; add the bot to your group or channel",
        ),
        SettingField(
            "telegram_chat",
            "str",
            label="Telegram chat",
            description="@channelname or the group's chat ID (-100…)",
        ),
        SettingField(
            "signal_url",
            "str",
            label="Signal REST API",
            description="https address of your signal-cli REST API",
        ),
        SettingField(
            "signal_number",
            "str",
            label="Signal number",
            description="The registered number that sends, e.g. +41791234567",
        ),
        SettingField(
            "signal_group",
            "str",
            label="Signal group ID",
            description="group.… from GET /v1/groups/<number>",
        ),
        SettingField("signal_token", "secret", label="Signal API token (optional)"),
        SettingField(
            "matrix_homeserver",
            "str",
            label="Matrix homeserver",
            description="e.g. https://matrix.org",
        ),
        SettingField("matrix_token", "secret", label="Matrix access token"),
        SettingField(
            "matrix_room",
            "str",
            label="Matrix room ID",
            description="!abc…:matrix.org; the account must be in the room",
        ),
    ),
    events={
        EVENT_PUBLISHED: f"{_HOOKS}:on_event_published",
        POST_PUBLISHED: f"{_HOOKS}:on_post_published",
        POLL_PUBLISHED: f"{_HOOKS}:on_poll_published",
        EVENT_REMINDER: f"{_HOOKS}:on_event_reminder",
        POLL_CLOSING: f"{_HOOKS}:on_poll_closing",
    },
    tasks=("hubra_messengers.tasks",),
    schedule=(
        Schedule("messengers-retry-minutely", "hubra_messengers.tasks.retry", 60.0),
    ),
    tables=("messengers_log",),
)
