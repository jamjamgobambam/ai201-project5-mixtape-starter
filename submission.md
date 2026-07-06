# AI Usage

I used AI assistance to navigate the unfamiliar Flask codebase, summarize file responsibilities, and trace route-to-service call chains. I asked for help identifying edge cases in suspicious service functions after reading the relevant files myself, then verified the explanations by running the existing tests and direct service-level checks. I used AI to draft and refine root cause analysis wording, but the diagnoses were checked against the code and test output before fixes were made.

# Codebase Map

## Main files and roles

- `app.py`: Flask application factory. It configures SQLAlchemy, registers the `songs`, `playlists`, `users`, and `feed` blueprints, and creates database tables inside the app context.
- `models.py`: Defines all SQLAlchemy data models and association tables:
  - `User` stores accounts, friendships, listening streak state, and relationships to songs, ratings, events, notifications, and playlists.
  - `Song` stores shared songs and metadata, including the original sharer and many-to-many tags.
  - `ListeningEvent` records each song listen with `user_id`, `song_id`, and `listened_at`.
  - `Rating` stores one score per user/song pair using a uniqueness constraint.
  - `Playlist` stores playlist metadata; `playlist_entries` is the join table that adds `position`, `added_by`, and `added_at`.
  - `Notification` stores user-facing notifications with type, body, created time, and read status.
- `routes/songs.py`: HTTP endpoints for searching songs, reading a song, rating a song, and recording a listen. The route layer parses request data and delegates to `search_service`, `notification_service`, or `streak_service`.
- `routes/playlists.py`: HTTP endpoints for creating playlists, reading playlist metadata, listing playlist songs, and adding a song to a playlist. Adding a song delegates to `notification_service.add_to_playlist()`.
- `routes/users.py`: HTTP endpoints for user profiles, streak lookup, notification lookup, and marking notifications read.
- `routes/feed.py`: HTTP endpoints for friends listening now and general activity feed, both delegated to `feed_service`.
- `services/streak_service.py`: Business logic for creating listening events and maintaining `User.listening_streak` / `User.last_listened_at`.
- `services/feed_service.py`: Builds feed response dictionaries from friends' `ListeningEvent` rows.
- `services/search_service.py`: Searches `Song` records by title or artist and serializes matching songs with tags.
- `services/notification_service.py`: Creates notifications and handles side effects when songs are added to playlists or rated.
- `services/playlist_service.py`: Creates playlists and retrieves playlist songs in join-table `position` order.
- `seed_data.py`: Rebuilds a local SQLite database with users, friendships, songs, tags, playlists, listening events, and sample notifications.
- `tests/`: Existing service-level pytest coverage for streak, search, and playlist behavior.

## Data flow example — user rates a song

1. Client sends `POST /songs/<song_id>/rate` with `user_id` and `score`.
2. `routes/songs.py` validates the required JSON fields and calls `notification_service.rate_song(user_id, song_id, score)`.
3. `rate_song()` validates that the score is 1–5, loads the `Song` and `User`, then checks whether a `Rating` already exists for that user/song pair.
4. If a rating exists, the score is updated; otherwise a new `Rating` row is added.
5. The database session is committed and the route returns `rating.to_dict()` as JSON.
6. Because notifications are also handled in `notification_service`, this is the correct place for any notification side effect when someone rates another user's shared song.

## Organization patterns noticed

- Routes are intentionally thin: they parse HTTP input, call a service, catch `ValueError`, and format JSON responses.
- The bugs are concentrated in the service layer, so debugging should trace from route to service rather than patching routes.
- Most response data is serialized through model `to_dict()` methods.
- Association tables (`friendships`, `song_tags`, `playlist_entries`) carry important behavior: friendships determine feeds, tags affect search joins, and playlist positions determine playlist ordering.

# Root Cause Analysis

## Issue #1 — My listening streak keeps resetting

### How you reproduced it

I reproduced this with the existing regression test `tests/test_streaks.py::test_streak_increments_on_sunday`. The test creates a user, calls `update_listening_streak()` for Saturday June 15, 2024, then calls it again for Sunday June 16, 2024. Before the fix, the user's streak stayed at `1` instead of increasing to `2`.

### How you found the root cause

I started from the reported feature path: `POST /songs/<song_id>/listen` in `routes/songs.py` calls `streak_service.record_listening_event()`, which creates a `ListeningEvent` and delegates streak math to `update_listening_streak()`. The failing test pointed to the same function. The specific cause became clear at the branch that handled consecutive days: the code only incremented when `days_since_last == 1 and today.weekday() != 6`.

### The root cause

The streak rules say any consecutive calendar day should increment the streak, including Saturday to Sunday. Python's `date.weekday()` returns `6` for Sunday, and the code explicitly excluded that value from the consecutive-day increment branch. As a result, listening on Sunday after listening on Saturday fell into the `else` branch and reset the streak to `1` even though no day was skipped.

### Your fix and side-effect check

I removed the Sunday exclusion so `days_since_last == 1` always increments the streak. This matches the documented rules in `streak_service.py`: same-day listens do not double count, exactly one day increments, and more than one skipped day resets. I ran `python -m pytest tests/test_streaks.py` to check the Sunday case plus the new-user, same-day, consecutive weekday, and skipped-day behavior.


