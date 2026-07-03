"""
tests/test_notifications.py — Mixtape

Regression tests for rating notifications (Issue #4).

These would have caught the bug where rate_song saved the rating but never
notified the song's original sharer (unlike add_to_playlist).
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
def sharer_and_rater(app):
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Golden Hour", artist="Solange K", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()
        yield {"sharer": sharer, "rater": rater, "song": song}


def test_rating_notifies_sharer(app, sharer_and_rater):
    """
    When a friend rates your song, you (the sharer) get a 'song_rated' notification.
    Before the fix, rate_song created no notification at all.
    """
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        rater = sharer_and_rater["rater"]
        song = sharer_and_rater["song"]

        assert get_notifications(sharer.id) == []
        rate_song(rater.id, song.id, 5)

        notifs = get_notifications(sharer.id)
        assert len(notifs) == 1
        assert notifs[0]["type"] == "song_rated"
        assert "rater" in notifs[0]["body"]
        assert "Golden Hour" in notifs[0]["body"]


def test_rating_own_song_does_not_notify(app, sharer_and_rater):
    """Rating your own song must not create a notification."""
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        song = sharer_and_rater["song"]

        rate_song(sharer.id, song.id, 4)
        assert get_notifications(sharer.id) == []
