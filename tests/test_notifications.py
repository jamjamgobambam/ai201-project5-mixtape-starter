"""Tests for notification behavior."""

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


@pytest.fixture
def rating_setup(app):
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        song = Song(title="Shared Track", artist="The Testers", shared_by=sharer.id)
        db.session.add_all([sharer, rater])
        db.session.flush()
        song.shared_by = sharer.id
        db.session.add(song)
        db.session.commit()
        yield {"sharer": sharer, "rater": rater, "song": song}


def test_rating_friend_song_notifies_original_sharer(app, rating_setup):
    """Rating a song shared by another user creates a notification."""
    with app.app_context():
        sharer = db.session.get(User, rating_setup["sharer"].id)
        rater = db.session.get(User, rating_setup["rater"].id)
        song = db.session.get(Song, rating_setup["song"].id)

        rate_song(rater.id, song.id, 5)

        notifications = db.session.query(Notification).filter_by(user_id=sharer.id).all()
        assert len(notifications) == 1
        assert notifications[0].notification_type == "song_rated"
        assert rater.username in notifications[0].body
        assert song.title in notifications[0].body


def test_rating_own_song_does_not_notify_self(app, rating_setup):
    """Users should not get notifications for rating their own songs."""
    with app.app_context():
        sharer = db.session.get(User, rating_setup["sharer"].id)
        song = db.session.get(Song, rating_setup["song"].id)

        rate_song(sharer.id, song.id, 4)

        notifications = db.session.query(Notification).filter_by(user_id=sharer.id).all()
        assert notifications == []
