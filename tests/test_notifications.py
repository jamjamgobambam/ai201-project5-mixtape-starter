"""
tests/test_notifications.py — Mixtape

Regression tests for notification creation on song ratings (Issue #4).

Before the fix, rate_song() saved the rating but never notified the song's
original sharer — unlike add_to_playlist(), which did. These tests would have
failed against the buggy version (0 notifications after a rating).
"""

import pytest
from app import create_app, db
from models import User, Song
from services.notification_service import rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed(app):
    """A sharer who owns a song, and a separate rater."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Neon City", artist="Synth Co", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()
        yield {"sharer": sharer, "rater": rater, "song": song}


def test_rating_notifies_the_sharer(app, seed):
    """A rating by another user creates a 'song_rated' notification for the sharer."""
    with app.app_context():
        sharer, rater, song = seed["sharer"], seed["rater"], seed["song"]
        assert get_notifications(sharer.id) == []

        rate_song(rater.id, song.id, 5)

        notifs = get_notifications(sharer.id)
        assert len(notifs) == 1  # Bug caused this to be 0
        assert notifs[0]["type"] == "song_rated"
        assert "Neon City" in notifs[0]["body"]


def test_rerating_does_not_duplicate_notification(app, seed):
    """Updating an existing rating's score should not create a second notification."""
    with app.app_context():
        sharer, rater, song = seed["sharer"], seed["rater"], seed["song"]
        rate_song(rater.id, song.id, 5)
        rate_song(rater.id, song.id, 3)  # score update, not a new rating
        assert len(get_notifications(sharer.id)) == 1


def test_rating_own_song_does_not_notify(app, seed):
    """A user rating their own shared song does not notify themselves."""
    with app.app_context():
        sharer, song = seed["sharer"], seed["song"]
        rate_song(sharer.id, song.id, 4)
        assert get_notifications(sharer.id) == []
