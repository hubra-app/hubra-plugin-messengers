"""The Messengers plugin: what is announced where, the URL checks, retries
and the board's page.

Runs with Hubra's fixtures once the plugin is in plugins/messengers of a
Hubra checkout (see README.md).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.helpers import set_modules
from tests.settings.test_settings_kv import _login, _make_role_and_member

BASE = "/api/v1/app/messengers"


@pytest.fixture
def club(client, app, db, seeded_db, monkeypatch):
    """Tom runs the messengers; Telegram and Matrix are set up, Signal isn't."""
    from hubra_messengers import services, transports

    set_modules(True, "messengers")
    app.test_cli_runner().invoke(args=["sync-permissions"])
    tier = seeded_db["tier"]
    tom = _make_role_and_member(
        db, tier, name="Tom", permission_keys=["messengers.channels.update"]
    )
    max_ = _make_role_and_member(db, tier, name="Max")
    cfg = {
        "announce_events": True,
        "announce_posts": True,
        "announce_polls": True,
        "announce_reminders": False,
        "members_only_events": False,
        "telegram_token": "123:abc",
        "telegram_chat": "@fcdemo",
        "matrix_homeserver": "https://matrix.example.org",
        "matrix_token": "mx-secret",
        "matrix_room": "!room:example.org",
    }
    monkeypatch.setattr(services, "config", lambda: cfg)
    # Example hosts don't resolve here; a public address stands in.
    monkeypatch.setattr(
        transports.socket,
        "getaddrinfo",
        lambda host, *a, **k: [(0, 0, 0, "", ("93.184.215.14", 443))],
    )
    sent, fail = [], {"n": 0}

    def fake(method, url, body, headers=None):
        if fail["n"]:
            fail["n"] -= 1
            raise transports.SendError("HTTP 502")
        sent.append((method, url, body, headers or {}))
        return {"ok": True, "result": {"message_id": 1}, "event_id": "$e"}

    monkeypatch.setattr(transports, "_request", fake)
    return {"tom": tom.id, "max": max_.id, "cfg": cfg, "sent": sent, "fail": fail}


def test_announces_what_the_whole_club_may_see(app, db, club):
    from hubra.core.models.event import ClubEvent
    from hubra.core.models.poll import Poll, PollOption
    from hubra_messengers import hooks
    from hubra_messengers.models import MessengersLog

    sent = club["sent"]
    with app.test_request_context():
        public = ClubEvent(
            title="Plauschturnier",
            date=date.today() + timedelta(days=9),
            time="14:00",
            type="event",
            is_public=True,
            location="Sportplatz",
        )
        inner = ClubEvent(
            title="Vorstandssitzung",
            date=date.today() + timedelta(days=3),
            type="meeting",
        )
        poll = Poll(question="Neues Vereinslokal?", created_by_id=club["tom"])
        db.session.add_all([public, inner, poll])
        db.session.flush()
        db.session.add_all(
            [
                PollOption(poll_id=poll.id, label="Ja"),
                PollOption(poll_id=poll.id, label="Nein"),
            ]
        )
        db.session.commit()

        hooks.on_event_published(event_id=public.id)
        hooks.on_event_published(event_id=public.id)  # published twice: announced once
        hooks.on_event_published(event_id=inner.id)  # members only: stays out
        hooks.on_poll_published(poll_id=poll.id)
        hooks.on_event_reminder(event_id=public.id)  # reminders are off
        db.session.commit()

    urls = [u for _, u, _, _ in sent]
    assert len(sent) == 4
    assert sum("api.telegram.org/bot123:abc/sendMessage" in u for u in urls) == 2
    assert (
        sum("/rooms/%21room%3Aexample.org/send/m.room.message/" in u for u in urls) == 2
    )
    tg = next(b for _, u, b, _ in sent if "telegram" in u)
    assert tg["chat_id"] == "@fcdemo" and tg["parse_mode"] == "HTML"
    assert (
        "<b>📅 Plauschturnier</b>" in tg["text"]
        and "14:00 Uhr" in tg["text"]
        and "📍 Sportplatz" in tg["text"]
    )
    mx = next(h for _, u, _, h in sent if "matrix" in u)
    assert mx["Authorization"] == "Bearer mx-secret"
    poll_text = [b for _, u, b, _ in sent if "telegram" in u][1]["text"]
    assert "• Ja" in poll_text and "• Nein" in poll_text
    assert db.session.query(MessengersLog).filter_by(status="sent").count() == 4

    # Members-only events, once the club says its groups are for members.
    club["cfg"]["members_only_events"] = True
    with app.test_request_context():
        hooks.on_event_published(event_id=inner.id)
        db.session.commit()
    assert len(sent) == 6


def test_post_published_through_hubra_reaches_the_messengers(app, db, club):
    from hubra.api.posts.services import PostsService

    with app.test_request_context():
        PostsService.create(
            {"title": "Neue Trikots sind da", "body": "Abholen am Mittwoch."},
            club["tom"],
        )
        db.session.commit()
    texts = [b.get("text", "") or b.get("body", "") for _, _, b, _ in club["sent"]]
    assert any("Neue Trikots sind da" in t for t in texts)


def test_retries_then_gives_up(app, db, club):
    from hubra_messengers import services
    from hubra_messengers.messages import Message
    from hubra_messengers.models import MessengersLog

    club["fail"]["n"] = 2 * services.MAX_TRIES  # two messengers, three tries each
    with app.test_request_context():
        assert services.announce("post", Message("Hallo"), "post:99") == 0
        db.session.commit()
        rows = db.session.query(MessengersLog).all()
        assert {r.status for r in rows} == {"queued"} and rows[0].error == "HTTP 502"
        services.retry()
        services.retry()
        db.session.commit()
    assert {r.status for r in db.session.query(MessengersLog).all()} == {"failed"}


def test_addresses_hubra_must_not_call(monkeypatch):
    from hubra_messengers import transports

    monkeypatch.setattr(
        transports.socket,
        "getaddrinfo",
        lambda host, *a, **k: [(0, 0, 0, "", ("10.0.0.5", 443))],
    )
    for bad in (
        "http://matrix.example.org",
        "https://u:p@matrix.example.org",
        "https://intern.example",
        "",
    ):
        with pytest.raises(transports.SendError):
            transports.check_url(bad)
    monkeypatch.setenv("MESSENGERS_PRIVATE_HOSTS", "signal-api")
    assert transports.check_url("http://signal-api:8080/") == "http://signal-api:8080"


def test_board_page_and_test_message(client, club):
    _login(client, "max@test.ch")
    assert client.get(f"{BASE}/status").status_code == 403

    _login(client, "tom@test.ch")
    got = client.get(f"{BASE}/status").get_json()
    assert [(c["channel"], c["configured"]) for c in got["channels"]] == [
        ("telegram", True),
        ("signal", False),
        ("matrix", True),
    ]
    assert client.post(f"{BASE}/test", json={"channel": "signal"}).status_code == 409
    assert client.post(f"{BASE}/test", json={"channel": "fax"}).status_code == 400

    club["fail"]["n"] = 1
    failed = client.post(f"{BASE}/test", json={"channel": "telegram"}).get_json()
    assert failed["status"] == "failed" and failed["error"] == "HTTP 502"
    assert "123:abc" not in str(failed)
    again = client.post(f"{BASE}/log/{failed['id']}/retry").get_json()
    assert again["status"] == "sent"
    log = client.get(f"{BASE}/log?channel=telegram").get_json()
    assert [r["kind"] for r in log] == ["test"]
    assert client.get(f"{BASE}/status").get_json()["channels"][0]["lastSentAt"]


def test_the_call_goes_to_the_checked_address(monkeypatch):
    # DNS rebinding: the name was public when the settings were saved (or
    # at check_url), and points into Hubra's own network at the call. The
    # connection checks the address it actually connects to.
    from hubra_messengers import transports

    answers = iter(["93.184.215.14", "127.0.0.1"])
    monkeypatch.setattr(
        transports.socket,
        "getaddrinfo",
        lambda host, *a, **k: [(0, 0, 0, "", (next(answers), 443))],
    )
    monkeypatch.setattr(
        transports.socket,
        "create_connection",
        lambda *a, **k: pytest.fail("connected to a private address"),
    )
    with pytest.raises(transports.SendError, match="private network"):
        url = transports.check_url("https://matrix.example.org")
        transports._request("POST", f"{url}/x", {})
