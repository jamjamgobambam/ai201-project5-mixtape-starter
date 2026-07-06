"""
tests/test_notification.py — Mixtape

Tests for notification service logic.
"""

import pytest
from app import create_app, db
from models import User, Song, Playlist, Notification, Rating
from services.notification_service import (
    create_notification,
    get_notifications,
    mark_as_read,
    add_to_playlist,
    rate_song,
)


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_data(app):
    """Create two users, a shared song, and a playlist for testing."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        other = User(username="other", email="other@example.com")
        db.session.add_all([sharer, other])
        db.session.flush()

        song = Song(title="Test Song", artist="Test Artist", shared_by=sharer.id)
        db.session.add(song)
        db.session.flush()

        playlist = Playlist(name="Test Playlist", created_by=other.id)
        db.session.add(playlist)
        db.session.commit()

        yield {
            "sharer_id": sharer.id,
            "other_id": other.id,
            "song_id": song.id,
            "playlist_id": playlist.id,
        }


# --- create_notification ---

def test_create_notification_returns_notification(app, seed_data):
    """create_notification should persist and return a Notification with read=False."""
    with app.app_context():
        notif = create_notification(
            user_id=seed_data["sharer_id"],
            notification_type="song_rated",
            body="Someone rated your song.",
        )
        assert notif.id is not None
        assert notif.notification_type == "song_rated"
        assert notif.body == "Someone rated your song."
        assert notif.read is False


# --- get_notifications ---

def test_get_notifications_returns_all(app, seed_data):
    """get_notifications should return all notifications for a user."""
    with app.app_context():
        user_id = seed_data["sharer_id"]
        create_notification(user_id, "song_rated", "First.")
        create_notification(user_id, "song_rated", "Second.")
        results = get_notifications(user_id)
        assert len(results) == 2


def test_get_notifications_unread_only(app, seed_data):
    """get_notifications with unread_only=True should return only unread notifications."""
    with app.app_context():
        user_id = seed_data["sharer_id"]
        notif = create_notification(user_id, "song_rated", "Will be read.")
        create_notification(user_id, "song_rated", "Still unread.")

        mark_as_read(notif.id)

        unread = get_notifications(user_id, unread_only=True)
        assert len(unread) == 1
        assert all(not n["read"] for n in unread)


def test_get_notifications_ordered_most_recent_first(app, seed_data):
    """get_notifications should return notifications newest-first."""
    with app.app_context():
        user_id = seed_data["sharer_id"]
        create_notification(user_id, "song_rated", "First notification.")
        create_notification(user_id, "song_rated", "Second notification.")
        results = get_notifications(user_id)
        assert results[0]["body"] == "Second notification."


# --- mark_as_read ---

def test_mark_as_read_marks_notification(app, seed_data):
    """mark_as_read should set the notification's read field to True."""
    with app.app_context():
        notif = create_notification(
            seed_data["sharer_id"], "song_rated", "Please read me."
        )
        assert notif.read is False
        mark_as_read(notif.id)
        updated = db.session.get(Notification, notif.id)
        assert updated.read is True


def test_mark_as_read_invalid_id_raises(app):
    """mark_as_read should raise ValueError for an unknown notification ID."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            mark_as_read("00000000-0000-0000-0000-000000000000")


# --- add_to_playlist ---

def test_add_to_playlist_adds_song_and_notifies_sharer(app, seed_data):
    """add_to_playlist should add the song and notify the original sharer."""
    with app.app_context():
        add_to_playlist(
            playlist_id=seed_data["playlist_id"],
            song_id=seed_data["song_id"],
            added_by_user_id=seed_data["other_id"],
        )
        notifications = get_notifications(seed_data["sharer_id"])
        assert len(notifications) == 1
        assert "Test Song" in notifications[0]["body"]
        assert notifications[0]["type"] == "song_added_to_playlist"


def test_add_to_playlist_no_notification_if_same_user(app, seed_data):
    """No notification should be created when the sharer adds their own song."""
    with app.app_context():
        sharer_id = seed_data["sharer_id"]
        own_playlist = Playlist(name="My List", created_by=sharer_id)
        db.session.add(own_playlist)
        db.session.commit()

        add_to_playlist(
            playlist_id=own_playlist.id,
            song_id=seed_data["song_id"],
            added_by_user_id=sharer_id,
        )
        notifications = get_notifications(sharer_id)
        assert len(notifications) == 0


def test_add_to_playlist_invalid_song_raises(app, seed_data):
    """add_to_playlist should raise ValueError for an unknown song ID."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            add_to_playlist(
                playlist_id=seed_data["playlist_id"],
                song_id="00000000-0000-0000-0000-000000000000",
                added_by_user_id=seed_data["other_id"],
            )


def test_add_to_playlist_invalid_user_raises(app, seed_data):
    """add_to_playlist should raise ValueError for an unknown user ID."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            add_to_playlist(
                playlist_id=seed_data["playlist_id"],
                song_id=seed_data["song_id"],
                added_by_user_id="00000000-0000-0000-0000-000000000000",
            )


def test_add_to_playlist_invalid_playlist_raises(app, seed_data):
    """add_to_playlist should raise ValueError for an unknown playlist ID."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            add_to_playlist(
                playlist_id="00000000-0000-0000-0000-000000000000",
                song_id=seed_data["song_id"],
                added_by_user_id=seed_data["other_id"],
            )


# --- rate_song ---

def test_rate_song_creates_rating(app, seed_data):
    """rate_song should create and return a Rating with the given score."""
    with app.app_context():
        rating = rate_song(
            user_id=seed_data["other_id"],
            song_id=seed_data["song_id"],
            score=4,
        )
        assert rating.score == 4
        assert rating.user_id == seed_data["other_id"]
        assert rating.song_id == seed_data["song_id"]


def test_rate_song_updates_existing_rating(app, seed_data):
    """Calling rate_song twice for the same user/song should update, not duplicate."""
    with app.app_context():
        rate_song(seed_data["other_id"], seed_data["song_id"], score=3)
        updated = rate_song(seed_data["other_id"], seed_data["song_id"], score=5)
        assert updated.score == 5

        all_ratings = db.session.query(Rating).filter_by(
            user_id=seed_data["other_id"], song_id=seed_data["song_id"]
        ).all()
        assert len(all_ratings) == 1


def test_rate_song_invalid_score_too_low_raises(app, seed_data):
    """rate_song should raise ValueError for a score below 1."""
    with app.app_context():
        with pytest.raises(ValueError, match="between 1 and 5"):
            rate_song(seed_data["other_id"], seed_data["song_id"], score=0)


def test_rate_song_invalid_score_too_high_raises(app, seed_data):
    """rate_song should raise ValueError for a score above 5."""
    with app.app_context():
        with pytest.raises(ValueError, match="between 1 and 5"):
            rate_song(seed_data["other_id"], seed_data["song_id"], score=6)


def test_rate_song_invalid_song_raises(app, seed_data):
    """rate_song should raise ValueError for an unknown song ID."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            rate_song(
                user_id=seed_data["other_id"],
                song_id="00000000-0000-0000-0000-000000000000",
                score=3,
            )


def test_rate_song_invalid_user_raises(app, seed_data):
    """rate_song should raise ValueError for an unknown user ID."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            rate_song(
                user_id="00000000-0000-0000-0000-000000000000",
                song_id=seed_data["song_id"],
                score=3,
            )


def test_rate_song_notifies_sharer(app, seed_data):
    """
    rate_song should create a notification for the song's original sharer.

    This test directly catches Bug #4: rate_song() saved the Rating but never
    called create_notification(), so the sharer received no alert. Without the
    notification block, get_notifications() returns an empty list here.
    """
    with app.app_context():
        rate_song(
            user_id=seed_data["other_id"],
            song_id=seed_data["song_id"],
            score=5,
        )
        notifications = get_notifications(seed_data["sharer_id"])
        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_rated"
        assert "Test Song" in notifications[0]["body"]


def test_rate_song_no_notification_if_sharer_rates_own_song(app, seed_data):
    """No notification should be created when the sharer rates their own song."""
    with app.app_context():
        rate_song(
            user_id=seed_data["sharer_id"],
            song_id=seed_data["song_id"],
            score=4,
        )
        notifications = get_notifications(seed_data["sharer_id"])
        assert len(notifications) == 0
