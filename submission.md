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

## Issue #5 — The last song in a playlist never shows up

### How you reproduced it

I reproduced this with the existing playlist tests. `tests/test_playlists.py::test_playlist_returns_all_songs` creates a playlist with five songs and expected five results, but `get_playlist_songs()` returned only four. `test_playlist_returns_songs_in_order` also showed that the returned titles stopped at `Track 4` and omitted `Track 5`.

### How you found the root cause

I traced `GET /playlists/<playlist_id>/songs` in `routes/playlists.py` to `playlist_service.get_playlist_songs()`. The query itself correctly joined `Song` to `playlist_entries`, filtered by playlist id, and ordered by `playlist_entries.position`. The specific problem was in the return statement after the query: it serialized `songs[:-1]` instead of `songs`.

### The root cause

`get_playlist_songs()` intentionally removed the final element from the ordered result list by slicing with `[:-1]`. Python list slicing excludes the stop index, so `songs[:-1]` means “all songs except the last one.” This made every non-empty playlist lose its final song even though the database query returned it correctly.

### Your fix and side-effect check

I changed the return statement to serialize the full `songs` list. This preserves the query's existing ordering and only removes the accidental truncation. I ran `python -m pytest tests/test_playlists.py` to verify playlists now return all five songs in order and empty playlists still return an empty list.

## Issue #4 — I got notified when a friend added my song to a playlist but not when they rated it

### How you reproduced it

I reproduced this by adding `tests/test_notifications.py::test_rating_song_notifies_original_sharer`. The test creates one user who shared a song and another user who rates it through `rate_song()`. Before the fix, querying `Notification` for the sharer raised `NoResultFound`, confirming that the rating was saved but no notification was created. I also added `test_rating_own_song_does_not_notify_self` to capture the expected self-notification guard.

### How you found the root cause

I traced `POST /songs/<song_id>/rate` in `routes/songs.py` to `notification_service.rate_song()`. I compared that function to the working playlist path: `routes/playlists.py` calls `notification_service.add_to_playlist()`, and `add_to_playlist()` both performs the playlist side effect and then calls `create_notification()` for the song's original sharer. The rating path lived in the same service but stopped after committing the `Rating` row.

### The root cause

The notification behavior was missing architecturally from the rating action. `rate_song()` validated the score, loaded the song and rater, inserted or updated the `Rating`, committed, and returned. Unlike `add_to_playlist()`, it never checked whether the actor was different from `song.shared_by` and never called `create_notification()`. The route was already calling the right service, but the service did not implement the expected notification side effect.

### Your fix and side-effect check

I added the same notification pattern used by playlist additions: after saving the rating, `rate_song()` now creates a `song_rated` notification for the original sharer unless the sharer rated their own song. I ran `python -m pytest tests/test_notifications.py tests/test_search.py tests/test_playlists.py tests/test_streaks.py` to verify the new notification behavior, the no-self-notification guard, and the existing service tests.

## Issue #2 — Friends Listening Now shows people from yesterday

### How you reproduced it

I reproduced this by adding `tests/test_feed.py::test_listening_now_excludes_yesterday_events`. The test creates a viewer with two friends: one listened 10 minutes ago and one listened 23 hours ago. Before the fix, `get_friends_listening_now()` returned both usernames, so the stale friend appeared in a feed that should represent current listening activity.

### How you found the root cause

I traced `GET /feed/<user_id>/listening-now` in `routes/feed.py` to `feed_service.get_friends_listening_now()`. That function calculates a cutoff using the module-level `RECENT_THRESHOLD`, filters friends' `ListeningEvent.listened_at` values against it, and then returns the newest event per friend. The filtering logic was structurally correct, so the key suspicious value was the threshold constant itself.

### The root cause

`RECENT_THRESHOLD` was set to `timedelta(hours=24)`. That made “Listening Now” mean “anything in the last day,” so a listen from yesterday but less than 24 hours old passed the filter. The rest of the query then correctly included that friend because, according to the overly broad cutoff, the event was still recent.

### Your fix and side-effect check

I changed `RECENT_THRESHOLD` to `timedelta(minutes=30)`, which matches the seeded data comments and the product meaning of “Listening Now”: very recent activity should appear, but yesterday's activity should not. I ran `python -m pytest tests/` to verify the new feed regression test and all existing streak, playlist, search, and notification tests passed.





