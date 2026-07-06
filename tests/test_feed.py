"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed logic.
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
def friends(app):
    """A user with one friend, connected one-directionally (user -> friend)."""
    with app.app_context():
        user = User(username="listener", email="listener@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([user, friend])
        db.session.flush()

        db.session.execute(
            friendships.insert().values(user_id=user.id, friend_id=friend.id)
        )

        song = Song(title="Test Song", artist="Test Artist", shared_by=friend.id)
        db.session.add(song)
        db.session.commit()

        yield {"user": user, "friend": friend, "song": song}


def test_shows_friend_listening_a_few_minutes_ago(app, friends):
    """A friend who listened a few minutes ago should show up as listening now."""
    with app.app_context():
        event = ListeningEvent(
            user_id=friends["friend"].id,
            song_id=friends["song"].id,
            listened_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db.session.add(event)
        db.session.commit()

        feed = get_friends_listening_now(friends["user"].id)
        assert len(feed) == 1
        assert feed[0]["friend"]["username"] == "friend"


def test_does_not_show_friend_listening_hours_ago(app, friends):
    """
    A friend who listened 2 hours ago should NOT show up as "listening now" --
    this feed is meant to reflect live/current activity, not a full day's
    lookback. Bug: RECENT_THRESHOLD was previously 24 hours, so a 2-hour-old
    event incorrectly still showed up as "listening now".
    """
    with app.app_context():
        event = ListeningEvent(
            user_id=friends["friend"].id,
            song_id=friends["song"].id,
            listened_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db.session.add(event)
        db.session.commit()

        feed = get_friends_listening_now(friends["user"].id)
        assert feed == []  # Bug caused this to incorrectly include the friend
