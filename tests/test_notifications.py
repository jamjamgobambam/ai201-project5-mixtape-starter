"""
tests/test_notifications.py — Mixtape

Regression tests for notification side effects.
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


def test_rate_song_creates_notification_for_original_sharer(app):
    """Rating a shared song should notify the original sharer."""
    with app.app_context():
        owner = User(username="owner", email="owner@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([owner, rater])
        db.session.flush()

        song = Song(title="Neon City", artist="Nova", shared_by=owner.id)
        db.session.add(song)
        db.session.commit()

        rate_song(rater.id, song.id, 4)

        notifications = db.session.query(Notification).filter_by(user_id=owner.id).all()
        assert len(notifications) == 1
        assert notifications[0].notification_type == "song_rated"
        assert "rated your song" in notifications[0].body


def test_rate_song_does_not_notify_when_owner_rates_own_song(app):
    """Users should not receive notifications for rating their own songs."""
    with app.app_context():
        owner = User(username="owner2", email="owner2@example.com")
        db.session.add(owner)
        db.session.flush()

        song = Song(title="Moonlight", artist="Echo", shared_by=owner.id)
        db.session.add(song)
        db.session.commit()

        rate_song(owner.id, song.id, 5)

        notifications = db.session.query(Notification).filter_by(user_id=owner.id).all()
        assert notifications == []
