# Mixtape Bug Hunt — Submission

## AI Usage

_To be completed in Milestone 4, after all bug fixes are done. Will describe how AI tools were used to navigate the codebase, trace call chains, and debug each issue — including anywhere the AI's explanation was incomplete or pointed in the wrong direction._

---

## Codebase Map

### Main files and their roles

- **`app.py`** — Flask application factory. Configures the database URI and secret key, initializes the shared `SQLAlchemy` instance, registers the four route blueprints (`songs`, `playlists`, `users`, `feed`), and creates all tables on startup.
- **`models.py`** — Defines all 7 SQLAlchemy models (`User`, `Tag`, `Song`, `ListeningEvent`, `Rating`, `Playlist`, `Notification`) plus 3 association tables: `friendships` (symmetric user-to-user), `song_tags` (plain many-to-many), and `playlist_entries` (many-to-many *with* extra columns: `position`, `added_by`, `added_at`). Every model has a `to_dict()` used to serialize it for JSON responses.
- **`routes/songs.py`, `routes/playlists.py`, `routes/users.py`, `routes/feed.py`** — Thin HTTP layer, one Flask blueprint per resource. Each route parses query params or JSON body, calls exactly one service function, and formats the JSON response and status code. No business logic lives here.
- **`services/streak_service.py`, `feed_service.py`, `search_service.py`, `notification_service.py`, `playlist_service.py`** — The business logic layer. All database queries, writes, and cross-entity logic (e.g., deciding whether to notify someone) live here, not in the routes.
- **`tests/test_streaks.py`, `test_search.py`, `test_playlists.py`** — Pytest suites covering streak update rules, search de-duplication, and playlist song ordering/completeness, each spinning up an in-memory SQLite DB per test via a shared `app` fixture.

### Data flow — adding a song to a playlist (and notifying the sharer)

This is the "working" notification pattern referenced in the issue list (Issue #4 compares this working case to a missing one), so it's a useful flow to have traced in full:

1. Client sends `POST /playlists/<playlist_id>/songs` with a JSON body `{song_id, added_by}`.
2. `routes/playlists.py:add_song()` validates that `song_id` and `added_by` are present (400 if not), then calls `notification_service.add_to_playlist(playlist_id, song_id, added_by_user_id)`.
3. `add_to_playlist()` looks up the `Song`, the adding `User`, and the `Playlist` by ID, raising `ValueError` (turned into a 400 by the route) if any is missing.
4. If the song isn't already in `playlist.songs`, it's appended and committed — this writes a new row into the `playlist_entries` association table with a `position`, `added_by`, and `added_at`.
5. It then checks `song.shared_by != added_by_user_id` — i.e., whether someone other than the original sharer added the song. If so, it calls `create_notification(user_id=song.shared_by, notification_type="song_added_to_playlist", body=...)`, which builds and commits a new `Notification` row.
6. The route returns `{"message": "Song added to playlist"}` with a 201 status to the client.

### Patterns noticed

- **Strict layering**: every route is a thin translator — parse input, call one service function, format the response. All queries and writes happen in `services/`, matching what the README states.
- **Centralized error handling**: nearly every service function starts by `db.session.get()`-ing a referenced record and raising a bare `ValueError` if it's missing. Routes catch that `ValueError` and turn it into a 400/404 JSON error — error handling is centralized in the route layer rather than duplicated per service.
- **UUID primary keys**: every model uses a string UUID (`generate_uuid()`) as its primary key instead of an auto-incrementing integer.
- **Association tables aren't all equal**: `playlist_entries` carries extra columns (`position`, `added_by`, `added_at`) beyond the plain FK pair, unlike `friendships` and `song_tags`, which are bare join tables. Playlist order is explicit data, not insertion order.
- **Dict serialization at the model level**: every model owns its own `to_dict()`, so services return plain dicts (not ORM objects) up to the routes, keeping `jsonify()` calls in the route layer simple.

---

## Root Cause Analysis

_To be completed one entry per bug fixed (at least 3), following Milestone 3. Each entry will cover: how the bug was reproduced, how the root cause was found, the root cause itself, and the fix + side-effect check._

### Issue #1 — My listening streak keeps resetting

**How I reproduced it:**

The bug only shows up on a Saturday → Sunday transition, and the real app always uses the live system clock (`datetime.now(timezone.utc)` in `record_listening_event`), so a normal `curl` call today couldn't trigger it. To exercise the real API route while controlling the date, I used Flask's `test_client()` (which routes a request through the actual blueprint → service → DB path, the same as a live HTTP call) combined with monkey-patching `datetime.now()` in a standalone script — no project source files were changed.

Using the seeded user `darius`:
1. Reset `darius`'s `last_listened_at` to `None` and `listening_streak` to `0` (clean starting state).
2. `POST /songs/<song_id>/listen` with `user_id=darius`, with the clock faked to Saturday, 2026-06-27 → response `201`, streak becomes `1` (correct: first listen ever).
3. `POST /songs/<song_id>/listen` again, same user, clock faked to the very next day, Sunday, 2026-06-28 (a consecutive day) → response `201`, but `GET /users/<darius_id>/streak` returns `{"streak": 1}` instead of the expected `2`.

Ran twice on two separate days, same result both times — confirmed reproducible.

**How I found the root cause:**

Read `update_listening_streak()` in `services/streak_service.py` top to bottom. Its own docstring documents exactly three rules: new user → streak starts at 1, listened today already → no change, listened yesterday → increment by 1. Nothing in the documented rules mentions a day-of-week exception. Comparing the code against that docstring line by line, the `elif` branch that's supposed to implement "listened yesterday → increment" reads `elif days_since_last == 1 and today.weekday() != 6:` — an extra clause not described anywhere in the docstring. That mismatch between documented behavior and actual code was the moment I was confident this was the exact bug, not just a suspicious area.

**The root cause:**

Python's `datetime.weekday()` returns `6` for Sunday. The condition `days_since_last == 1 and today.weekday() != 6` is true only when the user listened on a consecutive day *and* today isn't a Sunday. So on a Sunday, even though `days_since_last == 1` (a genuine consecutive-day listen), the `and` clause evaluates to `False`, the `elif` is skipped, and execution falls into the `else` branch, which sets `listening_streak = 1` — resetting the streak instead of incrementing it. This happens every week, specifically on Sundays, matching the user complaint that the streak "keeps resetting."

**Fix and side-effect check:**

Removed the `and today.weekday() != 6` clause, leaving `elif days_since_last == 1:` — matching the documented streak rules exactly, with no day-of-week special case. Checked for side effects: `update_listening_streak()` has exactly one caller in the whole codebase (`record_listening_event()` in the same file, called from `routes/songs.py`'s `POST /songs/<id>/listen` route) — nothing else depends on it. Ran the full test suite: all 5 tests in `test_streaks.py` pass, including `test_streak_increments_on_sunday` (previously latent/unasserted against the bug). Also re-ran the original reproduction script against the live API — streak now correctly goes `1 → 2` across the Saturday→Sunday boundary.

### Issue #3 — The same song keeps showing up twice in search (attempted, not yet reproduced)

**How I attempted to reproduce it:**

`search_songs()` does an unnecessary `outerjoin` to `song_tags` (a many-to-many association table) but never actually filters/selects on tag data — only `title`/`artist`. Confirmed at the raw `sqlite3` level (bypassing the ORM) that this join genuinely fans out: for a 3-tag song ("Crown Heights Anthem"), it produces 3 duplicate rows.

However, through the actual app code path — `db.session.query(Song).outerjoin(...).all()`, which is exactly what `search_songs()` runs — the duplication does not currently surface. Verified this four ways, all deduplicated to a single result: calling `search_songs()` directly, hitting the real `GET /songs/search` endpoint, running the project's own `pytest tests/test_search.py` (all 5 tests pass), and an unrelated sanity check joining `User` to `ListeningEvent`. The installed SQLAlchemy version (2.0.51) appears to auto-collapse duplicate parent rows for legacy `Query().all()` calls regardless of eager-loading config.

**Status:** parked for now — moving on to Issue #4, will revisit (may need the fuller issue description from the project brief, or a different repro angle).

### Issue #2 — Friends Listening Now shows people from yesterday

**How I reproduced it:**

Re-ran `seed_data.py` for a fresh, predictable dataset, then called the real `GET /feed/<user_id>/listening-now` endpoint (via Flask's `test_client()`, same route → service → DB path as a live call) for the seeded user `kenji`.

`kenji`'s only two friends are `nova` and `aaliya`. The response included `nova`, with her song `"Midnight Drive"` listed as the most recent event — but that event is **2 hours old**. `aaliya`'s event (34 hours old) was correctly excluded. `seed_data.py` itself documents the intent here: its "older events" comment block explicitly labels every event in that batch (2h, 10h, 18h, 26h, 34h, 42h, 50h, 58h old) as data that "should NOT appear in 'listening now' after fix" — yet several of them, including `nova`'s at 2h, currently do appear, because they fall inside the 24-hour `RECENT_THRESHOLD` window.

**How I found the root cause:**

Read `get_friends_listening_now()` in `services/feed_service.py`. The comparison logic itself (`listened_at >= cutoff`, `cutoff = now - RECENT_THRESHOLD`) is straightforward and correct — it does exactly what a "within the last X" filter should do. That narrowed the question to: is `X` (`RECENT_THRESHOLD`, defined as `timedelta(hours=24)`) the right value? A function named `get_friends_listening_now`, backing a feature called "Friends Listening Now," strongly implies live/current activity — not a full day's lookback. Cross-checking against `seed_data.py`'s own comments confirmed it: the "recent events" bucket is explicitly described as "within the past 30 minutes," while the "older events" bucket (2–58 hours old) is explicitly commented as data that "should NOT appear in 'listening now' after fix." That confirmed the 24-hour constant itself was the bug, not the surrounding logic.

**The root cause:**

`RECENT_THRESHOLD = timedelta(hours=24)` made the "listening now" filter accept anything played in the last 24 hours. Since the feature is meant to show truly current activity (on the order of minutes), a full-day window let stale plays — including ones from "yesterday" in the literal sense — leak into the feed. The filter logic wasn't wrong; the constant defining "recent" was simply set two orders of magnitude too generous.

**Fix and side-effect check:**

Changed `RECENT_THRESHOLD` from `timedelta(hours=24)` to `timedelta(minutes=30)`, matching the window `seed_data.py` itself was designed around. Checked callers: `RECENT_THRESHOLD` and `get_friends_listening_now()` are used in exactly one place (`routes/feed.py`'s `/listening-now` route); `get_activity_feed()` is a separate, unfiltered function unaffected by this constant. No dedicated test file exists for feed logic, so verified both sides of the boundary manually against the live API: `kenji`'s feed (previously wrongly showing `nova`'s 2-hour-old play) now correctly returns empty, while `nova`'s feed (3 friends with genuinely recent, <30-min-old plays) still correctly returns all 3 — confirming the fix doesn't break the legitimate "actually listening now" case.

### Issue #4 — I got notified when a friend added my song to a playlist but not when they rated it

**How I reproduced it:**

Used two seeded users: `nova` (who shared the song "Midnight Drive") and `darius` (a different user, not the sharer).

1. `GET /users/<nova_id>/notifications` before → count = 1 (just the pre-existing "song_added_to_playlist" notification from seed data).
2. `POST /songs/<song_id>/rate` with `user_id=darius`, `score=5` for nova's "Midnight Drive" → `201`, rating saved successfully.
3. `GET /users/<nova_id>/notifications` after → count is still 1 — no new notification was created for nova, even though someone other than the original sharer rated her song.

Contrast with the working case already traced in the Codebase Map: adding someone else's song to a playlist *does* call `create_notification(...)` for the sharer (`notification_service.add_to_playlist()`). `rate_song()` performs the equivalent save (a `Rating` instead of a playlist entry) but never calls `create_notification()` at all — confirmed reproducible.

**How I found the root cause:**

Per the brief's hint, compared `rate_song()` line-by-line against the working `add_to_playlist()` pattern in the same file. Both functions already fetch the acting user (`rater` / `adder`) and the `song`, and both perform their core write followed by `db.session.commit()`. `add_to_playlist()` has one more block after that: `if song.shared_by != added_by_user_id: create_notification(...)`. `rate_song()` simply `return`s after its commit — that missing block, not any typo in existing code, was the moment I was confident I'd found the actual cause.

**The root cause:**

`rate_song()` never calls `create_notification()` at all. It saves/updates the `Rating` row correctly, but the entire "check whether the actor is someone other than the sharer, then notify the sharer" step — present in `add_to_playlist()` — was never written for the rating path. This is architectural: not a broken condition, but an entire step missing from one of two structurally parallel functions.

**Fix and side-effect check:**

Added the same notify block used by `add_to_playlist()`, right after the rating is committed: if `song.shared_by != user_id`, call `create_notification(user_id=song.shared_by, notification_type="song_rated", body=f"{rater.username} rated your song '{song.title}' {score}/5.")` — reusing the `rater` and `song` objects already fetched earlier in the function, and the `"song_rated"` type string named in `create_notification()`'s own docstring example. Checked callers: `rate_song()` has exactly one call site (`routes/songs.py`'s `POST /songs/<id>/rate` route). Ran the full test suite (`11 passed`, 2 pre-existing failures from the still-unfixed Issue #5, unrelated) and re-ran the original reproduction: `nova`'s notification count now correctly goes from `1 → 2` when `darius` rates her song, with the new notification reading `"darius rated your song 'Midnight Drive' 5/5."`

### Issue #5 — The last song in a playlist never shows up

**How I reproduced it:**

Used the seeded playlist "Late Night Vibes" (created by `nova`, populated with 7 songs at positions 1–7 per `seed_data.py`).

1. Queried `playlist_entries` directly for this playlist → confirmed 7 rows, positions 1 through 7.
2. Called the real `GET /playlists/<playlist_id>/songs` endpoint → response `200`, but only **6** songs returned: "Midnight Drive," "Still Waters," "First Light," "Block Party," "Late Night Session," "Golden Hour" — positions 1–6, in correct order.
3. The 7th song, "Free Throws" (position 7 — the last one), is missing from the response entirely, even though it's really in the playlist.

Confirmed reproducible on the first try — not conditional like Issues #1/#3; every playlist with songs is missing its last entry.

**How I found the root cause:**

_TODO — Milestone 3._

**The root cause:**

_TODO — Milestone 3._

**Fix and side-effect check:**

_TODO — Milestone 3._

---

## git log Screenshot

_To be added in Milestone 4 — screenshot of `git log --oneline` on the `bugfix/mixtape` branch showing one commit per bug fix._
