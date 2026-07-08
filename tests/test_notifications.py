"""
tests/test_notifications.py — Mixtape

Tests for notification creation on song interactions.

Regression coverage for Issue #4: rating a friend's song must notify the
song's original sharer, mirroring the existing add-to-playlist behaviour.
"""

import pytest
from app import create_app, db
from models import User, Song, Notification
from services.notification_service import rate_song


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def sharer_and_song(app):
    """A sharer who owns a song, plus a separate rater."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(
            title="Crown Heights Anthem", artist="Borough Kings",
            genre="rap", shared_by=sharer.id,
        )
        db.session.add(song)
        db.session.commit()
        yield {"sharer": sharer, "rater": rater, "song": song}


def test_rating_notifies_the_sharer(app, sharer_and_song):
    """
    Regression for Issue #4: when a user rates someone else's song, the
    sharer receives exactly one 'song_rated' notification.
    """
    with app.app_context():
        sharer = sharer_and_song["sharer"]
        rater = sharer_and_song["rater"]
        song = sharer_and_song["song"]

        rate_song(rater.id, song.id, 5)

        notifs = (
            db.session.query(Notification)
            .filter_by(user_id=sharer.id, notification_type="song_rated")
            .all()
        )
        assert len(notifs) == 1
        assert "rater" in notifs[0].body
        assert song.title in notifs[0].body


def test_rating_own_song_does_not_notify(app, sharer_and_song):
    """A user rating their own shared song should not notify themselves."""
    with app.app_context():
        sharer = sharer_and_song["sharer"]
        song = sharer_and_song["song"]

        rate_song(sharer.id, song.id, 4)

        notifs = (
            db.session.query(Notification)
            .filter_by(user_id=sharer.id, notification_type="song_rated")
            .all()
        )
        assert notifs == []


def test_updating_a_rating_still_notifies(app, sharer_and_song):
    """
    Re-rating (the upsert path) still counts as a rating interaction and
    notifies the sharer each time.
    """
    with app.app_context():
        sharer = sharer_and_song["sharer"]
        rater = sharer_and_song["rater"]
        song = sharer_and_song["song"]

        rate_song(rater.id, song.id, 2)
        rate_song(rater.id, song.id, 5)  # update existing rating

        notifs = (
            db.session.query(Notification)
            .filter_by(user_id=sharer.id, notification_type="song_rated")
            .all()
        )
        assert len(notifs) == 2
