import pytest
from app import create_app, db
from models import User, Song, Rating, Notification
from services.notification_service import rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_data(app):
    with app.app_context():
        # User who shares the song
        sharer = User(username="sharer", email="sharer@example.com")
        # Friend who rates the song
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Crown Heights Anthem", artist="Borough Kings", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        yield {
            "sharer": sharer,
            "rater": rater,
            "song": song,
        }


def test_rate_song_creates_notification_for_sharer(app, seed_data):
    """
    Rating a song shared by another user should generate a notification for the sharer.
    """
    with app.app_context():
        sharer_id = seed_data["sharer"].id
        rater_id = seed_data["rater"].id
        song_id = seed_data["song"].id

        # Rater rates sharer's song
        rate_song(rater_id, song_id, 5)

        # Sharer should receive a notification
        notifications = get_notifications(sharer_id)
        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_rated"
        assert "rater rated your song 'Crown Heights Anthem' 5 stars." in notifications[0]["body"]


def test_rate_own_song_does_not_create_notification(app, seed_data):
    """
    Rating one's own song should not generate a notification.
    """
    with app.app_context():
        sharer_id = seed_data["sharer"].id
        song_id = seed_data["song"].id

        # Sharer rates their own song
        rate_song(sharer_id, song_id, 4)

        # Sharer should have NO notifications
        notifications = get_notifications(sharer_id)
        assert len(notifications) == 0
