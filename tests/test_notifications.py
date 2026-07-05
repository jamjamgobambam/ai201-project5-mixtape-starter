"""
tests/test_notifications.py — Mixtape

Tests for notification creation.

Regression coverage for Issue #4: "I got notified when a friend added my song
to a playlist but not when they rated it." Rating someone else's song must
notify the song's original sharer, mirroring the add-to-playlist behavior.
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
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Golden Hour", artist="Solange K", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()
        yield {"sharer": sharer, "rater": rater, "song": song}


def test_rating_notifies_sharer(app, seed):
    """Rating another user's song creates a notification for the sharer."""
    with app.app_context():
        rate_song(seed["rater"].id, seed["song"].id, 5)
        notifs = get_notifications(seed["sharer"].id)
        assert len(notifs) == 1
        assert notifs[0]["type"] == "song_rated"


def test_rating_own_song_does_not_notify(app, seed):
    """Rating your own song must not create a self-notification."""
    with app.app_context():
        rate_song(seed["sharer"].id, seed["song"].id, 4)
        notifs = get_notifications(seed["sharer"].id)
        assert notifs == []


def test_updating_rating_still_notifies(app, seed):
    """Re-rating a song still routes a notification to the sharer."""
    with app.app_context():
        rate_song(seed["rater"].id, seed["song"].id, 3)
        rate_song(seed["rater"].id, seed["song"].id, 5)
        notifs = get_notifications(seed["sharer"].id)
        # One notification per rate call, both addressed to the sharer.
        assert len(notifs) == 2
        assert all(n["type"] == "song_rated" for n in notifs)
