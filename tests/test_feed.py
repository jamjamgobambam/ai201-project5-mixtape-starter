"""
tests/test_feed.py — Mixtape

Tests for get_friends_listening_now.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent
from services.feed_service import get_friends_listening_now, RECENT_THRESHOLD


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def make_user(username):
    u = User(username=username, email=f"{username}@example.com")
    db.session.add(u)
    return u


def make_song(sharer_id, title="Song"):
    s = Song(title=title, artist="Artist", shared_by=sharer_id)
    db.session.add(s)
    return s


def make_event(user_id, song_id, listened_at):
    e = ListeningEvent(user_id=user_id, song_id=song_id, listened_at=listened_at)
    db.session.add(e)
    return e


def test_raises_for_unknown_user(app):
    """An unknown user_id raises ValueError."""
    with app.app_context():
        with pytest.raises(ValueError):
            get_friends_listening_now("does-not-exist")


def test_no_friends_returns_empty_list(app):
    """A user with no friends gets an empty feed."""
    with app.app_context():
        u = make_user("alice")
        db.session.commit()

        assert get_friends_listening_now(u.id) == []


def test_friend_with_no_listening_events_is_excluded(app):
    """A friend who has never listened to anything is excluded."""
    with app.app_context():
        u = make_user("alice")
        friend = make_user("bob")
        db.session.commit()
        u.friends.append(friend)
        db.session.commit()

        assert get_friends_listening_now(u.id) == []


def test_recent_event_is_included(app):
    """A friend's event within RECENT_THRESHOLD shows up in the feed."""
    with app.app_context():
        u = make_user("alice")
        friend = make_user("bob")
        db.session.commit()
        u.friends.append(friend)
        song = make_song(friend.id)
        db.session.commit()

        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        make_event(friend.id, song.id, recent_time)
        db.session.commit()

        feed = get_friends_listening_now(u.id)
        assert len(feed) == 1
        assert feed[0]["friend"]["username"] == "bob"
        assert feed[0]["song"]["id"] == song.id


def test_stale_event_is_excluded(app):
    """A friend's event older than RECENT_THRESHOLD is excluded."""
    with app.app_context():
        u = make_user("alice")
        friend = make_user("bob")
        db.session.commit()
        u.friends.append(friend)
        song = make_song(friend.id)
        db.session.commit()

        stale_time = datetime.now(timezone.utc) - RECENT_THRESHOLD - timedelta(minutes=1)
        make_event(friend.id, song.id, stale_time)
        db.session.commit()

        assert get_friends_listening_now(u.id) == []


def test_non_friend_events_are_excluded(app):
    """Listening events from users who are not friends never appear."""
    with app.app_context():
        u = make_user("alice")
        stranger = make_user("carol")
        db.session.commit()
        song = make_song(stranger.id)
        db.session.commit()

        make_event(stranger.id, song.id, datetime.now(timezone.utc))
        db.session.commit()

        assert get_friends_listening_now(u.id) == []


def test_only_most_recent_song_per_friend_is_shown(app):
    """When a friend has multiple recent events, only the latest is returned."""
    with app.app_context():
        u = make_user("alice")
        friend = make_user("bob")
        db.session.commit()
        u.friends.append(friend)
        older_song = make_song(friend.id, title="Older")
        newer_song = make_song(friend.id, title="Newer")
        db.session.commit()

        now = datetime.now(timezone.utc)
        make_event(friend.id, older_song.id, now - timedelta(minutes=20))
        make_event(friend.id, newer_song.id, now - timedelta(minutes=5))
        db.session.commit()

        feed = get_friends_listening_now(u.id)
        assert len(feed) == 1
        assert feed[0]["song"]["title"] == "Newer"


def test_multiple_friends_ordered_most_recent_first(app):
    """Multiple friends' events are returned ordered by most recent first."""
    with app.app_context():
        u = make_user("alice")
        bob = make_user("bob")
        carol = make_user("carol")
        db.session.commit()
        u.friends.append(bob)
        u.friends.append(carol)
        bob_song = make_song(bob.id, title="Bob Song")
        carol_song = make_song(carol.id, title="Carol Song")
        db.session.commit()

        now = datetime.now(timezone.utc)
        make_event(bob.id, bob_song.id, now - timedelta(minutes=15))
        make_event(carol.id, carol_song.id, now - timedelta(minutes=2))
        db.session.commit()

        feed = get_friends_listening_now(u.id)
        assert [entry["friend"]["username"] for entry in feed] == ["carol", "bob"]
