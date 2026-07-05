"""
tests/test_add_to_playlist.py — Mixtape

Regression coverage for the "add song to a playlist" feature. The
playlist_entries association table has NOT-NULL `position` and `added_by`
columns that a plain SQLAlchemy relationship append does not populate, which
raised sqlite3.IntegrityError. add_to_playlist must insert the entry row
explicitly with a computed position and the adding user.
"""

import pytest
from app import create_app, db
from models import User, Song, Playlist, playlist_entries
from services.notification_service import add_to_playlist
from services.playlist_service import get_playlist_songs


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
        adder = User(username="adder", email="adder@example.com")
        db.session.add_all([sharer, adder])
        db.session.flush()

        song = Song(title="Golden Hour", artist="Solange K", shared_by=sharer.id)
        db.session.add(song)
        db.session.flush()

        playlist = Playlist(name="Road Trip", created_by=adder.id)
        db.session.add(playlist)
        db.session.commit()
        yield {"sharer": sharer, "adder": adder, "song": song, "playlist": playlist}


def test_add_to_playlist_persists_entry_with_valid_position(app, seed):
    """Adding a song writes a playlist_entries row with a valid position."""
    with app.app_context():
        playlist_id = seed["playlist"].id
        song_id = seed["song"].id
        adder_id = seed["adder"].id

        add_to_playlist(playlist_id, song_id, adder_id)

        entry = db.session.query(playlist_entries).filter_by(
            playlist_id=playlist_id, song_id=song_id
        ).first()
        assert entry is not None
        assert entry.position is not None and entry.position >= 1
        assert entry.added_by == adder_id

        # The song is retrievable through the ordered playlist query.
        songs = get_playlist_songs(playlist_id)
        assert song_id in [s["id"] for s in songs]


def test_add_to_playlist_assigns_incrementing_positions(app, seed):
    """A second song is appended at the next position, not a duplicate."""
    with app.app_context():
        playlist_id = seed["playlist"].id
        adder_id = seed["adder"].id
        sharer_id = seed["sharer"].id

        second_song = Song(title="Cranes in the Sky", artist="Solange K", shared_by=sharer_id)
        db.session.add(second_song)
        db.session.commit()

        add_to_playlist(playlist_id, seed["song"].id, adder_id)
        add_to_playlist(playlist_id, second_song.id, adder_id)

        positions = [
            row.position
            for row in db.session.query(playlist_entries)
            .filter_by(playlist_id=playlist_id)
            .all()
        ]
        assert sorted(positions) == [1, 2]

        titles = [s["title"] for s in get_playlist_songs(playlist_id)]
        assert titles == ["Golden Hour", "Cranes in the Sky"]
