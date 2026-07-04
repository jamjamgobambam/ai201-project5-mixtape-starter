import pytest
from datetime import datetime, timedelta, timezone

from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now
from services.notification_service import rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_friends_listening_now_ignores_old_events(app):
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        viewer = User(username="viewer", email="viewer@example.com")
        db.session.add_all([sharer, viewer])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=viewer.id, friend_id=sharer.id))
        db.session.execute(friendships.insert().values(user_id=sharer.id, friend_id=viewer.id))

        recent_song = Song(title="Recent Hit", artist="Artist", shared_by=sharer.id)
        old_song = Song(title="Old Hit", artist="Artist", shared_by=sharer.id)
        db.session.add_all([recent_song, old_song])
        db.session.flush()

        now = datetime.now(timezone.utc)
        db.session.add(ListeningEvent(user_id=sharer.id, song_id=recent_song.id, listened_at=now - timedelta(minutes=10)))
        db.session.add(ListeningEvent(user_id=sharer.id, song_id=old_song.id, listened_at=now - timedelta(hours=2)))
        db.session.commit()

        results = get_friends_listening_now(viewer.id)
        assert len(results) == 1
        assert results[0]["song"]["title"] == "Recent Hit"


def test_rating_song_creates_notification_for_song_sharer(app):
    with app.app_context():
        sharer = User(username="songowner", email="owner@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Rated Song", artist="Artist", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        rate_song(rater.id, song.id, 5)
        notifications = get_notifications(sharer.id)

        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_rated"
        assert "rated your song" in notifications[0]["body"].lower()
