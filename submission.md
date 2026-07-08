# Mixtape Bug Hunt — Submission

## Codebase Map

### Top-level files

- **app.py** — Flask application factory (`create_app`). Initializes `SQLAlchemy` (`db`), registers four blueprints (`songs`, `playlists`, `users`, `feed`) under their respective URL prefixes, and calls `db.create_all()` on startup.
- **models.py** — Defines all SQLAlchemy models: `User`, `Tag`, `Song`, `ListeningEvent`, `Rating`, `Playlist`, `Notification`. Also defines three association tables: `friendships` (symmetric many-to-many between users), `song_tags` (many-to-many between songs and tags), and `playlist_entries` (many-to-many between playlists and songs, but with an explicit `position` column — songs in a playlist have an ordering, not just insertion order).
- **seed_data.py** — Populates the database with 5 users and their friendships, 10 tags, 13 songs (deliberately split into songs with 0, 1, and 3+ tags), a mix of recent and older listening events, 3 playlists, and one working notification. The varying tag counts on songs are clearly there to expose the search duplication bug.

### routes/ — thin controllers

Every route file follows the same pattern: parse the request, call a service function, format the response as JSON. No business logic lives in routes.

- **songs.py** → calls `search_service.search_songs` / `get_song`, `notification_service.rate_song`, `streak_service.record_listening_event`
- **playlists.py** → calls `playlist_service.create_playlist` / `get_playlist_songs` / `get_playlist`, `notification_service.add_to_playlist`
- **users.py** → calls `streak_service.get_streak`, `notification_service.get_notifications` / `mark_as_read`
- **feed.py** → calls `feed_service.get_friends_listening_now` / `get_activity_feed`

### services/ — where the business logic (and the bugs) live

- **streak_service.py** — `record_listening_event` creates a `ListeningEvent` row and calls `update_listening_streak`, which compares `user.last_listened_at.date()` to `today` to decide whether to increment, hold, or reset the streak.
- **feed_service.py** — `get_friends_listening_now` filters listening events to a 24-hour `RECENT_THRESHOLD` window, then deduplicates so only the most recent song per friend is shown.
- **search_service.py** — `search_songs` does an `outerjoin` against `song_tags` and filters by title/artist match, then calls `.to_dict()` on each row returned by the query.
- **notification_service.py** — `add_to_playlist` creates a `Notification` after adding a song to a playlist. `rate_song` saves a `Rating` but has no corresponding call to `create_notification` anywhere in the function.
- **playlist_service.py** — `get_playlist_songs` queries songs ordered by `position`, then returns `songs[:-1]` before mapping to dicts.

### Pattern I noticed

Every route delegates immediately to a service function — routes only parse input and shape the response; all logic and DB writes happen in `services/`. The `to_dict()` method on each model is the single serialization point, so any bug visible in JSON output usually traces back to either the query logic in a service function or a relationship defined in `models.py`.

### Data flow trace: user rates a song

1. Client sends `POST /songs/<song_id>/rate` with `user_id` and `score` in the JSON body.
2. `routes/songs.py::rate()` parses the body, validates that `user_id` and `score` are present, then calls `notification_service.rate_song(user_id, song_id, score)`.
3. `rate_song()` validates the score is between 1 and 5, confirms the song and user exist, checks whether a `Rating` already exists for that user/song pair (there's a unique constraint on `user_id` + `song_id`), then either updates the existing `Rating` or creates a new one, and commits.
4. The route serializes the returned `Rating` object back to the client as JSON.

Notably, `rate_song()` never calls `create_notification()`, unlike the parallel `add_to_playlist()` function in the same file, which explicitly notifies the song's original sharer after modifying the playlist. This asymmetry is the shape of Issue #4 — the rating is saved correctly, but no notification is ever generated for it.

---

## AI Usage

_(To be filled in throughout the project — will describe what I asked AI to explain, trace, or summarize, and where I had to verify or correct its explanation.)_

---

## Root Cause Analysis Entries

_(Full 5-field entries to be completed per bug in Milestone 3. Reproduction notes captured below while fresh, from Milestone 2.)_

### Issue #1 — My listening streak keeps resetting

**How I reproduced it:** In `flask shell`, called `update_listening_streak(user, saturday)` followed by `update_listening_streak(user, sunday)` using fixed `datetime` objects for a real consecutive Saturday/Sunday pair, bypassing the system clock so the exact dates were controlled. After the Saturday call the streak was 1; after the Sunday call (a consecutive day) the streak dropped back to 1 instead of incrementing to 2.

**How I found the root cause:** Navigated from the failing behavior straight to `streak_service.py`, since it's the only file that touches `listening_streak`. Read `update_listening_streak` top to bottom and found the three-branch conditional that decides whether to increment, hold, or reset the streak. The `elif` branch included an extra condition, `today.weekday() != 6`, that had no explanation in the docstring or comments. Checked what `datetime.weekday()` returns for a known Sunday date (`6`) and confirmed that was the exact day the bug reports named.

**The root cause:** The streak-increment branch was `elif days_since_last == 1 and today.weekday() != 6`. Python's `datetime.weekday()` returns `6` for Sunday (Monday=0 through Sunday=6). Because the condition explicitly excluded weekday `6`, any listen that fell on a Sunday and was otherwise a valid consecutive-day listen (`days_since_last == 1`) failed the `and` check and fell through to the `else` branch, which unconditionally reset the streak to 1. There is no legitimate reason a calendar weekday should affect whether a streak increments — the only two things that should matter are whether it's a new day and whether exactly one day has passed since the last listen.

**My fix and side-effect check:** Removed `and today.weekday() != 6` from the `elif` condition, leaving `elif days_since_last == 1:`. This is the smallest possible change that removes the erroneous weekday exclusion while leaving the same-day and skipped-day branches untouched. Verified by re-running the reproduction (Saturday → 1, Sunday → 2, as expected) and by running the full `test_streaks.py` suite: all 5 tests pass, including `test_streak_increments_on_sunday` (written to catch this exact bug) and the four pre-existing tests for new users, consecutive days, same-day no-double-count, and skipped-day resets, confirming no adjacent streak behavior was broken.

**Issue #1 — Streak resets on Sunday**
Reproduced via `flask shell`, bypassing the real system clock to control the exact dates involved. Called `update_listening_streak(user, saturday)` then `update_listening_streak(user, sunday)` with fixed `datetime` objects for a real Saturday/Sunday pair. Streak went from incrementing normally to resetting to 1 on the Sunday call, despite the two days being consecutive.

**Issue #2 — Friends Listening Now shows stale entries**
Reproduced via `flask shell`. Inserted a `ListeningEvent` for a friend (darius) timestamped at 11pm the previous calendar day, then called `get_friends_listening_now()` using the real current time (afternoon of the next day). The friend still appeared in the "listening now" feed with yesterday's timestamp, confirming the 24-hour rolling window (`RECENT_THRESHOLD = timedelta(hours=24)`) does not respect calendar-day boundaries.

**Issue #3 — Duplicate search results (investigated, not reproduced)**
Investigated via `flask shell` across multiple angles: raw SQL join (`Song.id` only) confirmed 3 duplicate rows for a 3-tag song; the same join through `search_songs()` (full ORM entities) consistently returned only 1 result, in a fresh session with no identity-map caching involved. Cross-checked against the existing test suite — all 5 tests in `test_search.py`, including `test_search_no_duplicates_multi_tag_song`, pass. Conclusion: the missing `.distinct()` is a real code smell and latent risk, but does not currently produce user-visible duplicates with the installed Flask-SQLAlchemy 3.1.1 stack, likely because full-entity ORM queries deduplicate by primary key in this version. Not fixed as one of the required 3; swapped for Issue #2.

**Issue #5 — Last playlist song missing**
Reproduced via live HTTP GET against a seeded playlist confirmed to have 7 rows in `playlist_entries`. `GET /playlists/<id>/songs` returned `count: 6`, missing the most recently added song.

**Issue #4 — Missing rating notification (stretch)**
Reproduced via live HTTP: `POST /songs/<id>/rate` with one user rating a song shared by a different user succeeded (score saved correctly), but `GET /users/<sharer_id>/notifications` for the song's original sharer returned `count: 0` — no notification was created.
