"""
tests/test_feed.py — Mixtape

Tests for feed service logic.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now, get_activity_feed


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_feed(app):
    """Create two friends with listening events for testing."""
    with app.app_context():
        user = User(username="me", email="me@example.com")
        friend = User(username="friend1", email="friend1@example.com")
        db.session.add_all([user, friend])
        db.session.flush()

        # Establish one-directional friendship: user -> friend
        db.session.execute(
            friendships.insert().values(user_id=user.id, friend_id=friend.id)
        )

        song1 = Song(title="Recent Song", artist="Artist A", shared_by=user.id)
        song2 = Song(title="Old Song", artist="Artist B", shared_by=user.id)
        db.session.add_all([song1, song2])
        db.session.flush()

        # Recent event (1 hour ago — within the 24h threshold)
        recent_event = ListeningEvent(
            user_id=friend.id,
            song_id=song1.id,
            listened_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        # Old event (30 hours ago — outside the 24h threshold)
        old_event = ListeningEvent(
            user_id=friend.id,
            song_id=song2.id,
            listened_at=datetime.now(timezone.utc) - timedelta(hours=30),
        )
        db.session.add_all([recent_event, old_event])
        db.session.commit()

        yield {
            "user_id": user.id,
            "friend_id": friend.id,
            "song1_id": song1.id,
            "song2_id": song2.id,
        }


# --- get_friends_listening_now ---

def test_get_friends_listening_now_returns_recent_event(app, seed_feed):
    """Friends who listened within 24 hours should appear in the feed."""
    with app.app_context():
        results = get_friends_listening_now(seed_feed["user_id"])
        songs = [r["song"]["title"] for r in results]
        assert "Recent Song" in songs


def test_get_friends_listening_now_excludes_old_events(app, seed_feed):
    """Events older than 24 hours should not appear in the feed."""
    with app.app_context():
        results = get_friends_listening_now(seed_feed["user_id"])
        songs = [r["song"]["title"] for r in results]
        assert "Old Song" not in songs


def test_get_friends_listening_now_deduplicates_per_friend(app, seed_feed):
    """Each friend should appear at most once (most recent event only)."""
    with app.app_context():
        # Add a second recent event for the same friend
        extra_event = ListeningEvent(
            user_id=seed_feed["friend_id"],
            song_id=seed_feed["song1_id"],
            listened_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.session.add(extra_event)
        db.session.commit()

        results = get_friends_listening_now(seed_feed["user_id"])
        friend_ids = [r["friend"]["id"] for r in results]
        assert len(friend_ids) == len(set(friend_ids))


def test_get_friends_listening_now_excludes_stale_events(app):
    """A friend who listened 20 hours ago should not appear in 'listening now'.

    This test directly catches Bug #2: RECENT_THRESHOLD was set to 24 hours,
    which incorrectly included friends who listened last night. A 20-hour-old
    event falls within the buggy 24-hour window but outside the correct 1-hour
    window, so this test fails before the fix and passes after.
    """
    with app.app_context():
        user = User(username="testuser", email="testuser@example.com")
        friend = User(username="stale_friend", email="stale@example.com")
        db.session.add_all([user, friend])
        db.session.flush()

        db.session.execute(
            friendships.insert().values(user_id=user.id, friend_id=friend.id)
        )

        song = Song(title="Last Night Song", artist="Artist X", shared_by=user.id)
        db.session.add(song)
        db.session.flush()

        db.session.add(ListeningEvent(
            user_id=friend.id,
            song_id=song.id,
            listened_at=datetime.now() - timedelta(hours=20),
        ))
        db.session.commit()

        results = get_friends_listening_now(user.id)
        assert results == []


def test_get_friends_listening_now_no_friends_returns_empty(app):
    """A user with no friends should get an empty feed."""
    with app.app_context():
        user = User(username="loner", email="loner@example.com")
        db.session.add(user)
        db.session.commit()
        results = get_friends_listening_now(user.id)
        assert results == []


def test_get_friends_listening_now_invalid_user_raises(app):
    """get_friends_listening_now should raise ValueError for an unknown user ID."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            get_friends_listening_now("00000000-0000-0000-0000-000000000000")


# --- get_activity_feed ---

def test_get_activity_feed_returns_friend_events(app, seed_feed):
    """get_activity_feed should return listening events from friends."""
    with app.app_context():
        results = get_activity_feed(seed_feed["user_id"])
        # Both recent and old events should appear (no recency filter)
        assert len(results) == 2
        usernames = [r["friend"]["username"] for r in results]
        assert all(u == "friend1" for u in usernames)


def test_get_activity_feed_orders_by_most_recent_first(app, seed_feed):
    """get_activity_feed should return events newest-first."""
    with app.app_context():
        results = get_activity_feed(seed_feed["user_id"])
        assert results[0]["song"]["title"] == "Recent Song"
        assert results[1]["song"]["title"] == "Old Song"


def test_get_activity_feed_respects_limit(app, seed_feed):
    """get_activity_feed should return at most `limit` events."""
    with app.app_context():
        results = get_activity_feed(seed_feed["user_id"], limit=1)
        assert len(results) == 1


def test_get_activity_feed_no_friends_returns_empty(app):
    """A user with no friends should get an empty activity feed."""
    with app.app_context():
        user = User(username="isolated", email="isolated@example.com")
        db.session.add(user)
        db.session.commit()
        results = get_activity_feed(user.id)
        assert results == []


def test_get_activity_feed_invalid_user_raises(app):
    """get_activity_feed should raise ValueError for an unknown user ID."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            get_activity_feed("00000000-0000-0000-0000-000000000000")
