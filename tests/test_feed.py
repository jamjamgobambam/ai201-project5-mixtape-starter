"""
tests/test_feed.py — Mixtape

Regression test for the "Friends Listening Now" recency window (Issue #2).
Before the fix the window was 24 hours, so a friend who listened hours ago
(or "yesterday") still appeared. test_listening_now_excludes_old_events would
have failed under the old 24-hour threshold.
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
    """A user with one friend who has both a recent and an old listening event."""
    with app.app_context():
        me = User(username="me", email="me@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([me, friend])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=me.id, friend_id=friend.id))

        recent_song = Song(title="Recent Jam", artist="A", shared_by=friend.id)
        old_song = Song(title="Old Jam", artist="B", shared_by=friend.id)
        db.session.add_all([recent_song, old_song])
        db.session.flush()

        now = datetime.now(timezone.utc)
        db.session.add(ListeningEvent(
            user_id=friend.id, song_id=recent_song.id, listened_at=now - timedelta(minutes=10)
        ))
        db.session.add(ListeningEvent(
            user_id=friend.id, song_id=old_song.id, listened_at=now - timedelta(hours=5)
        ))
        db.session.commit()
        yield {"me": me, "friend": friend}


def test_listening_now_includes_recent_event(app, seed):
    """A friend who listened minutes ago appears in the feed."""
    with app.app_context():
        feed = get_friends_listening_now(seed["me"].id)
        assert len(feed) == 1
        assert feed[0]["song"]["title"] == "Recent Jam"


def test_listening_now_excludes_old_events(app, seed):
    """
    A friend whose most recent listen was 5 hours ago must NOT appear.
    Under the old 24-hour window they incorrectly showed up.
    """
    with app.app_context():
        feed = get_friends_listening_now(seed["me"].id)
        titles = [f["song"]["title"] for f in feed]
        assert "Old Jam" not in titles
