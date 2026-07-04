"""
tests/test_search.py — Mixtape

Tests for song search logic.
"""

import pytest
from app import create_app, db
from models import User, Song, Tag, song_tags
from services.search_service import search_songs


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_songs(app):
    """Create a set of songs with varying tag counts for testing."""
    with app.app_context():
        user = User(username="sharer", email="sharer@example.com")
        db.session.add(user)
        db.session.flush()

        tag_rap = Tag(name="rap")
        tag_hiphop = Tag(name="hip-hop")
        tag_boom_bap = Tag(name="boom bap")
        tag_indie = Tag(name="indie")
        db.session.add_all([tag_rap, tag_hiphop, tag_boom_bap, tag_indie])
        db.session.flush()

        # Song with NO tags
        song_no_tags = Song(
            title="Midnight Drive", artist="The Wanderers",
            genre="indie rock", shared_by=user.id
        )

        # Song with ONE tag
        song_one_tag = Song(
            title="Block Party", artist="Street Collective",
            genre="hip-hop", shared_by=user.id
        )

        # Song with THREE tags — this one will duplicate in search results with the bug
        song_multi_tags = Song(
            title="Crown Heights Anthem", artist="Borough Kings",
            genre="rap", shared_by=user.id
        )

        db.session.add_all([song_no_tags, song_one_tag, song_multi_tags])
        db.session.flush()

        # Assign tags
        db.session.execute(
            song_tags.insert().values(song_id=song_one_tag.id, tag_id=tag_rap.id)
        )
        db.session.execute(
            song_tags.insert().values(song_id=song_multi_tags.id, tag_id=tag_rap.id)
        )
        db.session.execute(
            song_tags.insert().values(song_id=song_multi_tags.id, tag_id=tag_hiphop.id)
        )
        db.session.execute(
            song_tags.insert().values(song_id=song_multi_tags.id, tag_id=tag_boom_bap.id)
        )

        db.session.commit()
        yield {
            "user": user,
            "song_no_tags": song_no_tags,
            "song_one_tag": song_one_tag,
            "song_multi_tags": song_multi_tags,
        }


def test_search_returns_matching_songs(app, seed_songs):
    """A basic search returns songs whose title or artist matches the query."""
    with app.app_context():
        results = search_songs("Borough")
        titles = [r["title"] for r in results]
        assert "Crown Heights Anthem" in titles


def test_search_no_duplicates_single_tag_song(app, seed_songs):
    """A song with one tag should appear exactly once in search results."""
    with app.app_context():
        results = search_songs("Block Party")
        matching = [r for r in results if r["title"] == "Block Party"]
        assert len(matching) == 1


def test_search_no_duplicates_multi_tag_song(app, seed_songs):
    """
    A song with multiple tags should appear exactly once in search results.
    """
    with app.app_context():
        results = search_songs("Crown Heights")
        matching = [r for r in results if r["title"] == "Crown Heights Anthem"]
        assert len(matching) == 1  # Should be 1, bug causes it to be 3


def test_search_no_duplicates_no_tag_song(app, seed_songs):
    """A song with no tags should appear exactly once in search results."""
    with app.app_context():
        results = search_songs("Midnight Drive")
        matching = [r for r in results if r["title"] == "Midnight Drive"]
        assert len(matching) == 1


def test_search_returns_empty_for_no_match(app, seed_songs):
    """A search with no matching songs returns an empty list."""
    with app.app_context():
        results = search_songs("zzz_no_match_zzz")
        assert results == []


def test_search_no_duplicate_song_ids(app, seed_songs):
    """
    Regression test: search results should have unique song IDs.

    This catches issues where a join could cause the same song to appear
    multiple times in results. Without deduplication, a song with N tags
    would appear N times (one per join row). This test verifies each song
    appears only once by song ID.
    """
    with app.app_context():
        results = search_songs("Crown")
        song_ids = [r["id"] for r in results]
        assert len(song_ids) == len(set(song_ids)), "Duplicate song IDs found in search results"
