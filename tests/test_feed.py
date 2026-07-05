"""
tests/test_feed.py — Mixtape

Regression tests for the "Friends Listening Now" recency window (Issue #2).

Before the fix, RECENT_THRESHOLD was 24 hours, so a friend who listened hours
ago still showed up as "listening now". These tests pin the window to a short
recency band: a friend from a few hours ago must NOT appear, a friend from a
few minutes ago must.
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
def seed(app):
    """
    'me' is friends with 'fresh' (listened 5 min ago) and 'stale'
    (listened 3 hours ago).
    """
    with app.app_context():
        me = User(username="me", email="me@example.com")
        fresh = User(username="fresh", email="fresh@example.com")
        stale = User(username="stale", email="stale@example.com")
        db.session.add_all([me, fresh, stale])
        db.session.flush()

        for other in (fresh, stale):
            db.session.execute(friendships.insert().values(user_id=me.id, friend_id=other.id))
            db.session.execute(friendships.insert().values(user_id=other.id, friend_id=me.id))

        song = Song(title="Pulse", artist="Wave", shared_by=me.id)
        db.session.add(song)
        db.session.flush()

        now = datetime.now(timezone.utc)
        db.session.add(ListeningEvent(user_id=fresh.id, song_id=song.id,
                                      listened_at=now - timedelta(minutes=5)))
        db.session.add(ListeningEvent(user_id=stale.id, song_id=song.id,
                                      listened_at=now - timedelta(hours=3)))
        db.session.commit()
        yield {"me": me, "fresh": fresh, "stale": stale}


def test_listening_now_excludes_stale_listener(app, seed):
    """A friend who listened 3 hours ago must NOT appear in 'listening now'."""
    with app.app_context():
        feed = get_friends_listening_now(seed["me"].id)
        usernames = [item["friend"]["username"] for item in feed]
        assert "stale" not in usernames  # Bug (24h window) included this friend
        assert usernames == ["fresh"]
