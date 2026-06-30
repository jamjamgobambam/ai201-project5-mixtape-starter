"""
tests/test_notifications.py — Mixtape

Regression tests for notification creation when a song is rated (Issue #4).
Before the fix, rate_song saved the rating but never notified the song's
original sharer, so test_rating_notifies_sharer would have failed.
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

        song = Song(title="After Hours", artist="Night City", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()
        yield {"sharer": sharer, "rater": rater, "song": song}


def test_rating_notifies_sharer(app, seed):
    """Rating someone else's song creates a 'song_rated' notification for the sharer."""
    with app.app_context():
        rate_song(seed["rater"].id, seed["song"].id, 5)
        notifs = get_notifications(seed["sharer"].id)
        rated = [n for n in notifs if n["type"] == "song_rated"]
        assert len(rated) == 1
        assert "rater" in rated[0]["body"]
        assert "After Hours" in rated[0]["body"]


def test_rating_own_song_does_not_notify(app, seed):
    """A user rating their own song should not generate a notification."""
    with app.app_context():
        rate_song(seed["sharer"].id, seed["song"].id, 4)
        notifs = get_notifications(seed["sharer"].id)
        assert [n for n in notifs if n["type"] == "song_rated"] == []
