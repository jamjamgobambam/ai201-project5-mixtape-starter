"""
tests/test_feed.py — Mixtape

Tests for listening-now recency behavior.
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


def test_listening_now_excludes_yesterday_activity(app):
    """Friends who listened yesterday should not appear in listening-now feed."""
    with app.app_context():
        viewer = User(username="viewer", email="viewer@example.com")
        friend = User(username="friend", email="friend@example.com")
        owner = User(username="owner", email="owner@example.com")
        db.session.add_all([viewer, friend, owner])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=viewer.id, friend_id=friend.id))
        db.session.execute(friendships.insert().values(user_id=friend.id, friend_id=viewer.id))

        song = Song(title="Afterglow", artist="Pulse", shared_by=owner.id)
        db.session.add(song)
        db.session.flush()

        old_event = ListeningEvent(
            user_id=friend.id,
            song_id=song.id,
            listened_at=datetime.now(timezone.utc) - timedelta(hours=23),
        )
        db.session.add(old_event)
        db.session.commit()

        feed = get_friends_listening_now(viewer.id)
        assert feed == []


def test_listening_now_includes_recent_activity(app):
    """Friends with very recent activity should appear in listening-now feed."""
    with app.app_context():
        viewer = User(username="viewer2", email="viewer2@example.com")
        friend = User(username="friend2", email="friend2@example.com")
        owner = User(username="owner2", email="owner2@example.com")
        db.session.add_all([viewer, friend, owner])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=viewer.id, friend_id=friend.id))
        db.session.execute(friendships.insert().values(user_id=friend.id, friend_id=viewer.id))

        song = Song(title="Sunrise", artist="Static", shared_by=owner.id)
        db.session.add(song)
        db.session.flush()

        recent_event = ListeningEvent(
            user_id=friend.id,
            song_id=song.id,
            listened_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.session.add(recent_event)
        db.session.commit()

        feed = get_friends_listening_now(viewer.id)
        assert len(feed) == 1
        assert feed[0]["friend"]["id"] == friend.id
