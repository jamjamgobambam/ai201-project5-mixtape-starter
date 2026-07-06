# Mixtape Bug Hunt Submission

## AI Usage
I used GitHub Copilot (GPT-5.3-Codex) primarily for codebase orientation, call-chain tracing, and root-cause verification.

- During orientation, I asked for module summaries and traced route -> service -> model data flow to build a map before touching bug fixes.
- During debugging, I used AI assistance to compare similar code paths (for example, working playlist notification flow vs. missing rating notification flow) and to sanity-check date/time edge-case reasoning.
- I verified every diagnosis by reading the source directly and reproducing behavior with tests or controlled app-context scripts before applying a fix.
- One limitation I observed: plausible AI explanations are not enough by themselves; reproduction and source verification were necessary before making changes.

## Codebase Map (Orientation First)
### Main files and roles
- `app.py`: Flask app factory, SQLAlchemy initialization, and blueprint registration (`songs`, `playlists`, `users`, `feed`).
- `models.py`: SQLAlchemy schema for all core entities (`User`, `Song`, `ListeningEvent`, `Rating`, `Playlist`, `Notification`, `Tag`) plus join tables (`friendships`, `song_tags`, `playlist_entries`).
- `routes/`: HTTP layer only. Routes parse inputs and call service functions; they mostly avoid business logic.
  - `routes/songs.py`: search, song detail, rating, listen endpoints.
  - `routes/playlists.py`: playlist creation, detail, list songs, add song.
  - `routes/users.py`: user profile, streak, notifications, mark-read.
  - `routes/feed.py`: friends listening-now feed and activity feed.
- `services/`: business logic layer where all 5 listed bugs live.
  - `services/streak_service.py`: streak updates tied to listening events.
  - `services/feed_service.py`: listening-now recency filtering + activity feed.
  - `services/search_service.py`: song search query logic.
  - `services/notification_service.py`: create/retrieve notifications, rating and playlist side effects.
  - `services/playlist_service.py`: playlist creation and ordered song retrieval.
- `tests/`: service-level regression coverage for streak/search/playlist behavior.
- `seed_data.py`: deterministic-ish local dataset with users, songs, tags, playlists, listening events, and sample notifications.

### Data flow example: user rates a song and should notify original sharer
1. `POST /songs/<song_id>/rate` hits `rate()` in `routes/songs.py`.
2. Route validates JSON payload (`user_id`, `score`) and calls `rate_song(user_id, song_id, score)`.
3. `services/notification_service.py:rate_song()` validates score and entities, upserts a `Rating`, commits.
4. Expected side effect: if rater is not the original sharer, create a `Notification` for `Song.shared_by`.
5. `GET /users/<user_id>/notifications` in `routes/users.py` calls `get_notifications()` to return notifications.

### Pattern observed
A consistent architecture is used: routes do request/response concerns while services perform business logic and persistence. This made bug tracing faster by following route entrypoints into exactly one service function per feature.

## Root Cause Analysis

### 1) Issue #1 - My listening streak keeps resetting
1. Issue number and title
- Issue #1 - My listening streak keeps resetting

2. How I reproduced it
- Reproduced with existing test `tests/test_streaks.py::test_streak_increments_on_sunday`.
- Sequence: call `update_listening_streak` on Saturday then Sunday for the same user.
- Observed pre-fix behavior: streak was reset to `1` on Sunday instead of incrementing to `2`.

3. How I found the root cause
- Navigation path: route (`routes/songs.py` listen endpoint) -> `record_listening_event()` -> `update_listening_streak()` in `services/streak_service.py`.
- The confidence point was the explicit conditional `days_since_last == 1 and today.weekday() != 6`, which special-cased Sunday and directly matched the failing scenario.

4. The root cause
- The increment condition incorrectly excludes Sundays (`weekday() == 6`).
- For a valid consecutive day transition Saturday -> Sunday (`days_since_last == 1`), the code falls into the reset branch, causing an incorrect streak reset.

5. Your fix and side-effect check
- Fix: removed the Sunday exclusion and incremented streak whenever `days_since_last == 1`.
- Why it works: streak logic should be based on consecutive-day distance, not specific weekday values.
- Side-effect checks:
  - Ran streak tests to ensure same-day no-double-count and skipped-day reset still behave correctly.
  - Verified Sunday case now increments.

### 2) Issue #5 - The last song in a playlist never shows up
1. Issue number and title
- Issue #5 - The last song in a playlist never shows up

2. How I reproduced it
- Reproduced with existing tests:
  - `tests/test_playlists.py::test_playlist_returns_all_songs`
  - `tests/test_playlists.py::test_playlist_returns_songs_in_order`
- Observed pre-fix behavior: playlist returned 4 songs instead of 5 and was missing the final track.

3. How I found the root cause
- Navigation path: `GET /playlists/<playlist_id>/songs` in `routes/playlists.py` -> `get_playlist_songs()` in `services/playlist_service.py`.
- The confidence point was the final return expression using `songs[:-1]`, which always drops the last list item.

4. The root cause
- The function intentionally (but incorrectly) slices the query result with `[:-1]` before serializing.
- Because Python slicing excludes the last element in that form, every playlist response omits the final song regardless of playlist size.

5. Your fix and side-effect check
- Fix: changed return logic from iterating `songs[:-1]` to iterating all `songs`.
- Why it works: it returns the complete ordered query result without truncation.
- Side-effect checks:
  - Ran playlist tests for total count, ordering, and empty-playlist behavior.
  - Confirmed order remains position-based while now including the last track.

### 3) Issue #4 - Playlist notification works, rating notification missing
1. Issue number and title
- Issue #4 - I got notified when a friend added my song to a playlist but not when they rated it

2. How I reproduced it
- Reproduced in an app-context script before fixing:
  - Created `owner`, `friend`, and a song shared by `owner`.
  - Called `rate_song(friend.id, song.id, 4)`.
  - Queried `Notification` rows for `owner`.
- Observed pre-fix behavior: notification count was `0`.

3. How I found the root cause
- Navigation path: `routes/songs.py` rating endpoint -> `services/notification_service.py:rate_song()`.
- Compared this code path line-by-line with `add_to_playlist()`, which already creates notifications.
- Confidence point: `rate_song()` validated and saved ratings but had no notification side effect at all.

4. The root cause
- Architectural omission: the rating workflow persisted a `Rating` record but never invoked notification creation for the original song sharer.
- As a result, playlist-add events generated notifications while rating events did not, despite similar product expectations.

5. Your fix and side-effect check
- Fix:
  - Added notification creation in `rate_song()` after rating commit.
  - Notification is only created when `song.shared_by != user_id` to avoid self-notifications.
  - Added regression tests in `tests/test_notifications.py`:
    - verifies notification is created for non-owner rater,
    - verifies no notification for self-rating.
- Why it works: the missing side effect now mirrors the existing notification pattern used in other interaction workflows.
- Side-effect checks:
  - Ran new notification tests.
  - Re-ran relevant existing tests to ensure rating persistence behavior remains intact.

### 4) Issue #2 - Friends Listening Now shows people from yesterday
1. Issue number and title
- Issue #2 - Friends Listening Now shows people from yesterday

2. How I reproduced it
- Reproduced in a controlled app-context script before fixing:
  - Created a viewer and a friend relationship.
  - Inserted a `ListeningEvent` for the friend at `now - 23 hours`.
  - Called `get_friends_listening_now(viewer_id)`.
- Observed pre-fix behavior: feed count was `1` even though the activity was from yesterday.

3. How I found the root cause
- Navigation path: `routes/feed.py` listening-now endpoint -> `services/feed_service.py:get_friends_listening_now()`.
- Confidence point: `RECENT_THRESHOLD` was hardcoded to `timedelta(hours=24)`, which semantically includes yesterday events and conflicts with a "listening now" feed expectation.

4. The root cause
- The recency window was too broad (`24` hours).
- Any event from the prior day but still within the last day was treated as "now", so stale activity leaked into the live feed.

5. Your fix and side-effect check
- Fix:
  - Changed `RECENT_THRESHOLD` from `24 hours` to `30 minutes`.
  - Added `tests/test_feed.py` regression coverage:
    - `test_listening_now_excludes_yesterday_activity`
    - `test_listening_now_includes_recent_activity`
- Why it works: the feed now uses a short real-time window aligned with "listening now" intent.
- Side-effect checks:
  - Confirmed very recent events are still returned.
  - Confirmed older events no longer appear in listening-now results.
