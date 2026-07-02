# Codebase Map

## Overview
This repository is a small Flask application for Mixtape, a social music app where users can share songs, build playlists, rate music, track listening streaks, and view activity feeds.

## Main files and responsibilities
- app.py: creates the Flask app, configures SQLAlchemy, registers the blueprints, and initializes the database.
- models.py: defines the SQLAlchemy models for users, songs, playlists, ratings, listening events, tags, friendships, and notifications.
- routes/songs.py: exposes endpoints for searching songs, fetching song details, rating songs, and recording listens.
- routes/playlists.py: exposes endpoints for creating playlists, viewing playlist data, listing playlist songs, and adding songs to playlists.
- routes/users.py: exposes endpoints for viewing users, checking streaks, retrieving notifications, and marking notifications as read.
- routes/feed.py: exposes endpoints for the “Friends Listening Now” feed and the general activity feed.
- services/search_service.py: handles song search and single-song lookup.
- services/notification_service.py: creates notifications and handles notification-producing actions such as adding songs to playlists.
- services/streak_service.py: records listening events and updates a user’s streak based on the time between listens.
- services/feed_service.py: builds the listening-now and activity feed from friend listening events.
- services/playlist_service.py: handles playlist creation and ordered playlist-song retrieval.
- seed_data.py: populates the database with starter content for development and testing.
- tests/: contains regression tests for streaks, search, and playlist behavior.

## Data flow example: adding a song to a playlist creates a notification
A real flow in the app looks like this:
1. A client sends a request to POST /playlists/<playlist_id>/songs in routes/playlists.py.
2. The route validates the request and calls add_to_playlist from services/notification_service.py.
3. The service loads the song, the playlist, and the user who added the song.
4. If the song is not already in the playlist, it appends the song to the playlist.
5. The service checks who originally shared the song using song.shared_by.
6. If that sharer is not the same person who added the song, the service creates a Notification record for the sharer.
7. The notification can later be fetched through the notifications route in routes/users.py.

## Data flow example: listening to a song updates streaks
When a user listens to a song:
1. The client sends a request to POST /songs/<song_id>/listen.
2. routes/songs.py calls record_listening_event in services/streak_service.py.
3. The service creates a ListeningEvent row and updates the user’s last_listened_at and listening_streak fields.
4. The change is committed to the database.

## Patterns I noticed
- The app uses a classic Flask blueprint structure: each feature area has its own route module.
- Routes are thin and mostly handle request parsing and JSON formatting; business logic lives in services/.
- The database layer is centered in models.py, with SQLAlchemy models and helper to_dict() methods used to serialize objects.
- The code favors small, explicit functions over large classes.
- Shared state is coordinated through the Flask-SQLAlchemy db session created in app.py.

---

# Root Cause Analysis

## Issue #1: My listening streak keeps resetting

**How I reproduced it:**
Constructed a `User` with `listening_streak=5` and `last_listened_at` set to Saturday, Jan 7 2023, 8:00 PM UTC, then called `update_listening_streak()` directly with `now` set to Sunday, Jan 8 2023, 9:00 AM UTC — exactly one calendar day later, which by the function's own docstring ("If the user listened yesterday: streak increments by 1") should bump the streak to 6. Instead the streak reset to 1. The condition is date-dependent: I confirmed `days_since_last == 1` was true (one consecutive day) but `today.weekday()` evaluated to `6` (Sunday) on the "now" side, which is what flips the outcome from increment to reset.

## Issue #2: Friends Listening Now shows people from yesterday

**How I reproduced it:**
Seeded the database with `seed_data.py` and called `get_friends_listening_now()` as `kenji`, whose friend `nova` has a `ListeningEvent` from 2 hours before the call (from the "older events" block in `seed_data.py`) with no more recent event to mask it. With the original `RECENT_THRESHOLD = timedelta(hours=24)`, the result included nova, listed as currently listening to "Midnight Drive" despite having listened 2 hours earlier. I confirmed the threshold was the cause by rerunning the exact same call with `RECENT_THRESHOLD` set to `timedelta(minutes=5)` (monkey-patched in a scratch script between calls, rather than editing and reverting the file) — nova dropped out of the result.

**How I found the root cause:**
Started at `routes/feed.py` to find the endpoint behind "Friends Listening Now" and followed the call into `services/feed_service.get_friends_listening_now()`. The function builds `cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD` and filters `ListeningEvent.listened_at >= cutoff` — that filter is the only place recency is enforced anywhere downstream (the per-friend loop below it just picks the most recent event per friend from whatever the query already returned). That narrowed it to either the cutoff calculation or the `RECENT_THRESHOLD` constant, and the constant was defined right above the function as `timedelta(hours=24)`. Seeing a 24-hour window on a feature named "listening now" was the moment I was confident — a full day is not "now" by any reasonable definition, and nothing else in the function constrains recency.

**The root cause:**
`RECENT_THRESHOLD` was set to `timedelta(hours=24)` instead of a short, live window. The query logic itself is correct — `listened_at >= cutoff` does filter out events older than the cutoff — but because the cutoff was computed from a 24-hour-wide threshold, any listen from up to a day ago passed the filter and was presented as an in-progress listen. The function has no other mechanism for judging "is this happening now" — that guarantee rests entirely on `RECENT_THRESHOLD` being small, so a threshold sized like a daily digest window caused yesterday's listens to be shown as live ones.

**Your fix and side-effect check:**
Changed `RECENT_THRESHOLD` from `timedelta(hours=24)` to `timedelta(minutes=5)` in `services/feed_service.py` — a one-line change, since the query logic around it was already correct. Afterward I checked `get_activity_feed()` in the same file, since it's the other consumer of listening events: it doesn't reference `RECENT_THRESHOLD` at all and just returns the most recent N events regardless of age, so it's unaffected. I also reran the seeded "recent" events (10, 15, 20 minutes old, added by `seed_data.py` with a comment saying they should appear in "listening now") against the fixed 5-minute threshold and found they're now excluded too, since they're older than 5 minutes by the time the app runs — a seed-data timing mismatch, not a defect in the fix, but worth noting since `seed_data.py` will need to be rerun immediately before demoing this feature or have its offsets tightened.

## Issue #4: I got notified when a friend added my song to a playlist but not when they rated it

**How I reproduced it:**
Seeded the database, found the song "Midnight Drive" shared by `nova`, and captured `get_notifications(nova.id)` before any new activity — 1 notification (a pre-existing seeded "added to playlist" notification). Then called `rate_song(user_id=darius.id, song_id=<midnight drive id>, score=5)` as `darius`, a different user than the sharer. Re-fetched `get_notifications(nova.id)` afterward and got the same 1 notification, with no new `song_rated` entry added — confirming `rate_song()` never calls `create_notification()`, unlike `add_to_playlist()`, which does check `song.shared_by` and notify the sharer.