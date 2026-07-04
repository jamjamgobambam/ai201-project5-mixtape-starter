"""
tests/test_ratings.py — Mixtape

Tests for song rating logic and the notifications it triggers.
"""

import pytest
from app import create_app, db
from models import Notification, Rating, Song, User
from services.notification_service import rate_song


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def sharer(app):
    with app.app_context():
        u = User(username="sharer", email="sharer@example.com")
        db.session.add(u)
        db.session.commit()
        yield u


@pytest.fixture
def rater(app):
    with app.app_context():
        u = User(username="rater", email="rater@example.com")
        db.session.add(u)
        db.session.commit()
        yield u


@pytest.fixture
def song(app, sharer):
    with app.app_context():
        s = Song(title="Test Song", artist="Test Artist", shared_by=sharer.id)
        db.session.add(s)
        db.session.commit()
        yield s


def test_rate_song_creates_rating(app, rater, song):
    """Rating a song creates a Rating with the given score."""
    with app.app_context():
        rating = rate_song(rater.id, song.id, 4)
        assert rating.score == 4
        assert rating.user_id == rater.id
        assert rating.song_id == song.id


def test_rate_song_notifies_sharer(app, rater, song):
    """Rating a friend's song notifies the person who shared it."""
    with app.app_context():
        rate_song(rater.id, song.id, 5)

        notifications = db.session.query(Notification).filter_by(
            user_id=song.shared_by
        ).all()
        assert len(notifications) == 1
        assert notifications[0].notification_type == "song_rated"
        assert "rater" in notifications[0].body


def test_rate_song_does_not_notify_self(app, sharer, song):
    """Rating your own song does not generate a notification."""
    with app.app_context():
        rate_song(sharer.id, song.id, 3)

        notifications = db.session.query(Notification).filter_by(
            user_id=sharer.id
        ).all()
        assert len(notifications) == 0


def test_rate_song_does_not_renotify_on_update(app, rater, song):
    """Updating an existing rating does not send a second notification."""
    with app.app_context():
        rate_song(rater.id, song.id, 2)
        rate_song(rater.id, song.id, 5)

        notifications = db.session.query(Notification).filter_by(
            user_id=song.shared_by
        ).all()
        assert len(notifications) == 1

        rating = db.session.query(Rating).filter_by(
            user_id=rater.id, song_id=song.id
        ).first()
        assert rating.score == 5
