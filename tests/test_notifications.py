"""
tests/test_notifications.py — Mixtape

Tests for notification side effects.
"""

import pytest
from app import create_app, db
from models import Notification, Song, User
from services.notification_service import rate_song


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_rating_song_notifies_original_sharer(app):
    """Rating someone else's shared song should notify the original sharer."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Shared Track", artist="Friend Band", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        rate_song(rater.id, song.id, 5)

        notification = db.session.query(Notification).filter_by(user_id=sharer.id).one()
        assert notification.notification_type == "song_rated"
        assert "rater rated your song 'Shared Track'" in notification.body


def test_rating_own_song_does_not_notify_self(app):
    """Users should not receive notifications for rating their own shared songs."""
    with app.app_context():
        user = User(username="artist", email="artist@example.com")
        db.session.add(user)
        db.session.flush()

        song = Song(title="Own Track", artist="Artist", shared_by=user.id)
        db.session.add(song)
        db.session.commit()

        rate_song(user.id, song.id, 4)

        notifications = db.session.query(Notification).filter_by(user_id=user.id).all()
        assert notifications == []
