"""
tests/test_feed.py — Mixtape

Tests for Friends Listening Now feed logic.
"""

from datetime import datetime, timedelta, timezone

import pytest
from app import create_app, db
from models import ListeningEvent, Song, User, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_listening_now_excludes_yesterday_events(app):
    """Friends Listening Now should show current activity, not yesterday's listens."""
    with app.app_context():
        user = User(username="viewer", email="viewer@example.com")
        recent_friend = User(username="recent", email="recent@example.com")
        stale_friend = User(username="stale", email="stale@example.com")
        db.session.add_all([user, recent_friend, stale_friend])
        db.session.flush()

        db.session.execute(
            friendships.insert().values(user_id=user.id, friend_id=recent_friend.id)
        )
        db.session.execute(
            friendships.insert().values(friend_id=user.id, user_id=recent_friend.id)
        )
        db.session.execute(
            friendships.insert().values(user_id=user.id, friend_id=stale_friend.id)
        )
        db.session.execute(
            friendships.insert().values(friend_id=user.id, user_id=stale_friend.id)
        )

        recent_song = Song(title="Right Now", artist="The Currents", shared_by=user.id)
        stale_song = Song(title="Yesterday", artist="Old News", shared_by=user.id)
        db.session.add_all([recent_song, stale_song])
        db.session.flush()

        now = datetime.now(timezone.utc)
        db.session.add_all(
            [
                ListeningEvent(
                    user_id=recent_friend.id,
                    song_id=recent_song.id,
                    listened_at=now - timedelta(minutes=10),
                ),
                ListeningEvent(
                    user_id=stale_friend.id,
                    song_id=stale_song.id,
                    listened_at=now - timedelta(hours=23),
                ),
            ]
        )
        db.session.commit()

        feed = get_friends_listening_now(user.id)
        usernames = [item["friend"]["username"] for item in feed]

        assert "recent" in usernames
        assert "stale" not in usernames
