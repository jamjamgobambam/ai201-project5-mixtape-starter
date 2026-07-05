"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed logic.

Regression coverage for Issue #2: "Friends Listening Now shows people from
yesterday." The feed must only surface friends who listened within the recent
window (30 minutes), not everyone who listened in the last day.
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


@pytest.fixture
def seed_feed(app):
    """A user with one friend and a song the friend can listen to."""
    with app.app_context():
        me = User(username="me", email="me@example.com")
        friend = User(username="friend", email="friend@example.com")
        sharer = User(username="sharer", email="sharer@example.com")
        db.session.add_all([me, friend, sharer])
        db.session.flush()

        # me <-> friend (only the direction me -> friend is needed for the query)
        db.session.execute(friendships.insert().values(user_id=me.id, friend_id=friend.id))

        song = Song(title="Neon City", artist="Static Era", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()
        yield {"me": me, "friend": friend, "song": song}


def _listen(friend_id, song_id, ago):
    db.session.add(
        ListeningEvent(
            user_id=friend_id,
            song_id=song_id,
            listened_at=datetime.now(timezone.utc) - ago,
        )
    )
    db.session.commit()


def test_recent_listen_appears(app, seed_feed):
    """A friend who listened 10 minutes ago appears in 'listening now'."""
    with app.app_context():
        _listen(seed_feed["friend"].id, seed_feed["song"].id, timedelta(minutes=10))
        feed = get_friends_listening_now(seed_feed["me"].id)
        assert len(feed) == 1


def test_hours_old_listen_excluded(app, seed_feed):
    """
    A friend who listened 3 hours ago must NOT appear in 'listening now'.
    Before the fix, the 24-hour threshold surfaced people from yesterday.
    """
    with app.app_context():
        _listen(seed_feed["friend"].id, seed_feed["song"].id, timedelta(hours=3))
        feed = get_friends_listening_now(seed_feed["me"].id)
        assert feed == []


def test_boundary_just_inside_window(app, seed_feed):
    """A listen 29 minutes ago is inside the 30-minute window."""
    with app.app_context():
        _listen(seed_feed["friend"].id, seed_feed["song"].id, timedelta(minutes=29))
        feed = get_friends_listening_now(seed_feed["me"].id)
        assert len(feed) == 1
