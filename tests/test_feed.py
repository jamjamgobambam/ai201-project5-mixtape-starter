"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed logic (README issue #2:
"Friends Listening Now shows people from yesterday").
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now
from services.streak_service import record_listening_event


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def users(app):
    with app.app_context():
        me = User(username="me", email="me@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([me, friend])
        db.session.commit()
        db.session.execute(friendships.insert().values(user_id=me.id, friend_id=friend.id))
        db.session.execute(friendships.insert().values(user_id=friend.id, friend_id=me.id))
        db.session.commit()
        yield me.id, friend.id


def _add_listening_event(app, friend_id, listened_at):
    with app.app_context():
        song = Song(title="Test Song", artist="Test Artist", shared_by=friend_id)
        db.session.add(song)
        db.session.commit()

        event = ListeningEvent(user_id=friend_id, song_id=song.id, listened_at=listened_at)
        db.session.add(event)
        db.session.commit()


def test_friend_listening_within_last_24_hours_is_shown(app, users):
    """A friend who listened within the last 24 hours should appear in the feed."""
    me_id, friend_id = users
    recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    _add_listening_event(app, friend_id, recent)

    with app.app_context():
        feed = get_friends_listening_now(me_id)
        assert len(feed) == 1
        assert feed[0]["friend"]["id"] == friend_id


def test_friend_listening_more_than_24_hours_ago_is_not_shown(app, users):
    """A friend who listened more than 24 hours ago (yesterday) should NOT appear
    in the "Friends Listening Now" feed."""
    me_id, friend_id = users
    yesterday = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=30)
    _add_listening_event(app, friend_id, yesterday)

    with app.app_context():
        feed = get_friends_listening_now(me_id)
        assert feed == []


def test_friend_listening_just_under_24_hours_ago_is_shown(app, users):
    """A friend who listened just under 24 hours ago should still appear."""
    me_id, friend_id = users
    just_under = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=23, minutes=59)
    _add_listening_event(app, friend_id, just_under)

    with app.app_context():
        feed = get_friends_listening_now(me_id)
        assert len(feed) == 1
        assert feed[0]["friend"]["id"] == friend_id


def test_friend_last_listened_at_reflects_latest_same_day_listen(app, users):
    """
    Regression test for README issue #2 ("Friends Listening Now shows people
    from yesterday"): update_listening_streak() only refreshed
    User.last_listened_at on a user's FIRST listen of a calendar day. A friend
    who listened again later the same day would still show last_listened_at
    from their earlier listen, which can appear to be "yesterday" once enough
    wall-clock time has passed. Each feed entry's friend.last_listened_at
    should reflect the most recent listen, not just the first one that day.
    """
    me_id, friend_id = users

    with app.app_context():
        song = Song(title="Song A", artist="Artist", shared_by=friend_id)
        db.session.add(song)
        db.session.commit()
        song_id = song.id

        # First listen of the day.
        record_listening_event(friend_id, song_id)
        friend = db.session.get(User, friend_id)
        first_listen_at = friend.last_listened_at

        # Second listen later the same day should refresh last_listened_at,
        # not leave it pinned to the first listen.
        record_listening_event(friend_id, song_id)
        friend = db.session.get(User, friend_id)
        assert friend.last_listened_at > first_listen_at

        feed = get_friends_listening_now(me_id)
        assert len(feed) == 1
        assert feed[0]["friend"]["last_listened_at"] == friend.last_listened_at.isoformat()
