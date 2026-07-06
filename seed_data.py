"""
seed_data.py — Mixtape

Populates the database with realistic test data.
Run with: python seed_data.py

This script creates:
- 5 users with established friendships
- 25 songs with varying tag counts (0, 1, and 3+ tags)
- 3 playlists with 5-10 songs each
- Listening events spanning the past 2 weeks (including recent ones)
- Existing streaks for some users
- Existing playlist-add notifications
"""

from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, Tag, Playlist, ListeningEvent, Rating, Notification, song_tags, playlist_entries, friendships


def seed():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        now = datetime.now(timezone.utc)

        # --- Users ---
        users = [
            User(username="nova",    email="nova@mixtape.app",    listening_streak=7),
            User(username="darius",  email="darius@mixtape.app",  listening_streak=3),
            User(username="simone",  email="simone@mixtape.app",  listening_streak=0),
            User(username="kenji",   email="kenji@mixtape.app",   listening_streak=12),
            User(username="aaliya",  email="aaliya@mixtape.app",  listening_streak=1),
        ]
        db.session.add_all(users)
        db.session.flush()

        # Establish friendships (bidirectional)
        def add_friendship(u1, u2):
            db.session.execute(friendships.insert().values(user_id=u1.id, friend_id=u2.id))
            db.session.execute(friendships.insert().values(user_id=u2.id, friend_id=u1.id))

        add_friendship(users[0], users[1])  # nova <-> darius
        add_friendship(users[0], users[2])  # nova <-> simone
        add_friendship(users[0], users[3])  # nova <-> kenji
        add_friendship(users[1], users[2])  # darius <-> simone
        add_friendship(users[3], users[4])  # kenji <-> aaliya

        # --- Tags ---
        tag_names = ["rap", "hip-hop", "boom bap", "r&b", "indie", "lo-fi",
                     "jazz", "soul", "electronic", "afrobeats"]
        tags = {name: Tag(name=name) for name in tag_names}
        db.session.add_all(tags.values())
        db.session.flush()

        # --- Songs ---
        # Songs with 0 tags
        song_data_no_tags = [
            ("Midnight Drive",    "The Wanderers",    "indie rock"),
            ("Still Waters",      "Elara Moon",       "ambient"),
            ("First Light",       "Coastal Highway",  "indie"),
        ]
        # Songs with 1 tag
        song_data_one_tag = [
            ("Block Party",        "Street Collective", "hip-hop",  ["hip-hop"]),
            ("Late Night Session", "Nova Blix",         "lo-fi",    ["lo-fi"]),
            ("Golden Hour",        "Solange K",         "r&b",      ["r&b"]),
            ("Free Throws",        "Hoop Dreams",       "rap",      ["rap"]),
            ("Soft Landing",       "Elara Moon",        "indie",    ["indie"]),
        ]
        # Songs with 3+ tags — these are the ones that expose Issue #3
        song_data_multi_tags = [
            ("Crown Heights Anthem", "Borough Kings",     "rap",      ["rap", "hip-hop", "boom bap"]),
            ("Harlem Renaissance",   "Uptown Collective", "hip-hop",  ["rap", "hip-hop", "soul"]),
            ("After Hours",          "Night City",        "r&b",      ["r&b", "soul", "jazz"]),
            ("Lagos to London",      "Afrowave",          "afrobeats", ["afrobeats", "electronic", "r&b"]),
            ("Frequencies",          "Static Era",        "electronic", ["electronic", "lo-fi", "indie"]),
        ]

        all_songs = []

        for title, artist, genre in song_data_no_tags:
            s = Song(title=title, artist=artist, genre=genre, shared_by=users[0].id,
                     shared_at=now - timedelta(days=5))
            db.session.add(s)
            all_songs.append((s, []))

        for title, artist, genre, tag_list in song_data_one_tag:
            s = Song(title=title, artist=artist, genre=genre, shared_by=users[1].id,
                     shared_at=now - timedelta(days=3))
            db.session.add(s)
            all_songs.append((s, tag_list))

        for title, artist, genre, tag_list in song_data_multi_tags:
            s = Song(title=title, artist=artist, genre=genre, shared_by=users[2].id,
                     shared_at=now - timedelta(days=1))
            db.session.add(s)
            all_songs.append((s, tag_list))

        db.session.flush()

        for song, tag_list in all_songs:
            for tag_name in tag_list:
                db.session.execute(
                    song_tags.insert().values(song_id=song.id, tag_id=tags[tag_name].id)
                )

        # --- Listening Events ---
        # Recent events (within the last 30 minutes) — should appear in "listening now".
        db.session.add(ListeningEvent(
            user_id=users[1].id,
            song_id=all_songs[0][0].id,
            listened_at=now - timedelta(minutes=10),
        ))
        db.session.add(ListeningEvent(
            user_id=users[3].id,
            song_id=all_songs[2][0].id,
            listened_at=now - timedelta(minutes=20),
        ))

        # Stale event (20 hours ago) — outside the 1-hour "listening now" window.
        # BUG DEMONSTRATION: with the original 24-hour RECENT_THRESHOLD this
        # event incorrectly appears in the feed. After the fix (1 hour) it is excluded.
        db.session.add(ListeningEvent(
            user_id=users[2].id,
            song_id=all_songs[1][0].id,
            listened_at=now - timedelta(hours=20),
        ))

        # Older events (2+ days ago) — should never appear in "listening now"
        for i in range(8):
            song = all_songs[i % len(all_songs)][0]
            user = users[i % len(users)]
            db.session.add(ListeningEvent(
                user_id=user.id,
                song_id=song.id,
                listened_at=now - timedelta(days=2 + i),
            ))

        # Set last_listened_at for streak users
        users[0].last_listened_at = now - timedelta(hours=1)
        users[1].last_listened_at = now - timedelta(minutes=10)
        users[2].last_listened_at = now - timedelta(hours=20)
        users[3].last_listened_at = now - timedelta(minutes=20)

        # --- Playlists ---
        playlists = [
            Playlist(name="Late Night Vibes", created_by=users[0].id),
            Playlist(name="Friday Energy",    created_by=users[1].id),
            Playlist(name="Study Mode",       created_by=users[3].id),
        ]
        db.session.add_all(playlists)
        db.session.flush()

        # Populate playlists with 5-7 songs
        playlist_song_sets = [
            [s for s, _ in all_songs[:7]],
            [s for s, _ in all_songs[3:10]],
            [s for s, _ in all_songs[5:12]],
        ]

        for playlist, song_set in zip(playlists, playlist_song_sets):
            for i, song in enumerate(song_set):
                db.session.execute(
                    playlist_entries.insert().values(
                        playlist_id=playlist.id,
                        song_id=song.id,
                        position=i + 1,
                        added_by=playlist.created_by,
                        added_at=now - timedelta(days=2),
                    )
                )

        # --- Notifications ---
        # Create some working "song added to playlist" notifications
        # so students can see the correct pattern when investigating Issue #4
        existing_song = all_songs[0][0]
        adder = users[1]
        playlist = playlists[0]
        notification = Notification(
            user_id=users[0].id,
            notification_type="song_added_to_playlist",
            body=f"{adder.username} added your song '{existing_song.title}' to the playlist '{playlist.name}'.",
        )
        db.session.add(notification)

        db.session.commit()
        print("Seed data created successfully.")
        print(f"  Users: {len(users)}")
        print(f"  Songs: {len(all_songs)}")
        print(f"  Playlists: {len(playlists)}")
        print(f"  Tags: {len(tags)}")


if __name__ == "__main__":
    seed()
