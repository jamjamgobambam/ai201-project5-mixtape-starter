"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed.

Regression coverage for Issue #2: the feed must only surface friends who are
active *now* (a short window), not anyone who listened in the last 24 hours.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def _friend(u1, u2):
    """Create a one-directional friendship row (feed reads user.friends)."""
    db.session.execute(friendships.insert().values(user_id=u1.id, friend_id=u2.id))


@pytest.fixture
def feed_world(app):
    """
    A viewer with two friends:
    - 'fresh' listened 15 minutes ago  -> should appear in "listening now"
    - 'stale' listened 3 hours ago     -> should NOT appear (within 24h, but not "now")
    """
    with app.app_context():
        now = datetime.now(timezone.utc)
        viewer = User(username="viewer", email="viewer@example.com")
        fresh = User(username="fresh", email="fresh@example.com")
        stale = User(username="stale", email="stale@example.com")
        db.session.add_all([viewer, fresh, stale])
        db.session.flush()

        _friend(viewer, fresh)
        _friend(viewer, stale)

        song = Song(title="Frequencies", artist="Static Era",
                    genre="electronic", shared_by=viewer.id)
        db.session.add(song)
        db.session.flush()

        db.session.add(ListeningEvent(
            user_id=fresh.id, song_id=song.id,
            listened_at=now - timedelta(minutes=15),
        ))
        db.session.add(ListeningEvent(
            user_id=stale.id, song_id=song.id,
            listened_at=now - timedelta(hours=3),
        ))
        db.session.commit()
        yield {"viewer": viewer, "fresh": fresh, "stale": stale, "song": song, "now": now}


def test_only_currently_active_friends_appear(app, feed_world):
    """A friend from 3 hours ago must not show up in 'listening now'."""
    with app.app_context():
        feed = get_friends_listening_now(feed_world["viewer"].id)
        usernames = {entry["friend"]["username"] for entry in feed}
        assert usernames == {"fresh"}  # 'stale' (3h ago) is excluded


def test_feed_dedupes_to_most_recent_per_friend(app, feed_world):
    """If a friend has several recent events, only the latest one appears."""
    with app.app_context():
        viewer = feed_world["viewer"]
        fresh = feed_world["fresh"]
        song = feed_world["song"]
        now = feed_world["now"]

        # Add an older-but-still-recent event for 'fresh'
        db.session.add(ListeningEvent(
            user_id=fresh.id, song_id=song.id,
            listened_at=now - timedelta(minutes=25),
        ))
        db.session.commit()

        feed = get_friends_listening_now(viewer.id)
        fresh_entries = [e for e in feed if e["friend"]["username"] == "fresh"]
        assert len(fresh_entries) == 1


def test_no_friends_returns_empty(app):
    """A user with no friends gets an empty feed, not an error."""
    with app.app_context():
        loner = User(username="loner", email="loner@example.com")
        db.session.add(loner)
        db.session.commit()
        assert get_friends_listening_now(loner.id) == []
