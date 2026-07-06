"""
tests/test_feed.py — Mixtape

Regression tests for Friends Listening Now feed logic.
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
    with app.app_context():
        viewer = User(username="viewer", email="viewer@example.com")
        friend_recent = User(username="friend_recent", email="recent@example.com")
        friend_stale = User(username="friend_stale", email="stale@example.com")
        db.session.add_all([viewer, friend_recent, friend_stale])
        db.session.flush()

        db.session.execute(
            friendships.insert().values(user_id=viewer.id, friend_id=friend_recent.id)
        )
        db.session.execute(
            friendships.insert().values(user_id=friend_recent.id, friend_id=viewer.id)
        )
        db.session.execute(
            friendships.insert().values(user_id=viewer.id, friend_id=friend_stale.id)
        )
        db.session.execute(
            friendships.insert().values(user_id=friend_stale.id, friend_id=viewer.id)
        )

        song = Song(title="Test Track", artist="Test Artist", shared_by=viewer.id)
        db.session.add(song)
        db.session.flush()

        now = datetime.now(timezone.utc)
        db.session.add(
            ListeningEvent(
                user_id=friend_recent.id,
                song_id=song.id,
                listened_at=now - timedelta(minutes=15),
            )
        )
        db.session.add(
            ListeningEvent(
                user_id=friend_stale.id,
                song_id=song.id,
                listened_at=now - timedelta(hours=3),
            )
        )
        db.session.commit()
        yield {"viewer": viewer, "friend_recent": friend_recent, "friend_stale": friend_stale}


def test_listening_now_excludes_stale_events(app, seed_feed):
    """Friends Listening Now should only include events within the recent window."""
    with app.app_context():
        feed = get_friends_listening_now(seed_feed["viewer"].id)
        friend_ids = {entry["friend"]["id"] for entry in feed}
        assert seed_feed["friend_recent"].id in friend_ids
        assert seed_feed["friend_stale"].id not in friend_ids
