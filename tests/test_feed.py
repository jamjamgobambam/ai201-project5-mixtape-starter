"""
tests/test_feed.py — Mixtape

Regression tests for the "Friends Listening Now" feed (Issue #2).

These would have caught the bug where RECENT_THRESHOLD was 24 hours, causing
friends who last listened hours (or up to a day) ago to appear as "listening now".
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


def _add_friendship(u1, u2):
    """Friendships are stored bidirectionally, mirroring seed_data.py."""
    db.session.execute(friendships.insert().values(user_id=u1.id, friend_id=u2.id))
    db.session.execute(friendships.insert().values(user_id=u2.id, friend_id=u1.id))


@pytest.fixture
def two_friends(app):
    """Create a viewer and one friend who has shared a song."""
    with app.app_context():
        viewer = User(username="viewer", email="viewer@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([viewer, friend])
        db.session.flush()
        _add_friendship(viewer, friend)

        song = Song(title="Neon City", artist="Synth Co", shared_by=friend.id)
        db.session.add(song)
        db.session.commit()
        yield {"viewer": viewer, "friend": friend, "song": song}


def _listen(friend, song, minutes_ago):
    now = datetime.now(timezone.utc)
    db.session.add(ListeningEvent(
        user_id=friend.id,
        song_id=song.id,
        listened_at=now - timedelta(minutes=minutes_ago),
    ))
    db.session.commit()


def test_recent_listen_appears(app, two_friends):
    """A friend who listened a few minutes ago IS shown as listening now."""
    with app.app_context():
        _listen(two_friends["friend"], two_friends["song"], minutes_ago=5)
        feed = get_friends_listening_now(two_friends["viewer"].id)
        assert len(feed) == 1
        assert feed[0]["friend"]["username"] == "friend"


def test_listen_two_hours_ago_is_excluded(app, two_friends):
    """
    A friend whose only listen was 2 hours ago must NOT appear in 'listening now'.
    With the old 24h RECENT_THRESHOLD this returned the friend (the bug).
    """
    with app.app_context():
        _listen(two_friends["friend"], two_friends["song"], minutes_ago=120)
        feed = get_friends_listening_now(two_friends["viewer"].id)
        assert feed == []


def test_yesterday_listen_is_excluded(app, two_friends):
    """A listen from ~25 hours ago ('yesterday') must not appear."""
    with app.app_context():
        _listen(two_friends["friend"], two_friends["song"], minutes_ago=25 * 60)
        feed = get_friends_listening_now(two_friends["viewer"].id)
        assert feed == []
