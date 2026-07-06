# Mixtape Bug Hunt — Submission

## AI Usage

I used Claude (Claude Code) throughout this project as a navigation and investigation partner, not as a bug-finder. Specifically:

**Codebase orientation (Milestone 1):** Before touching any issue, I had Claude read every file in `services/`, `routes/`, `app.py`, `models.py`, and `tests/`, and produce a 2-sentence summary per file plus a 1-sentence description of what each individual method/function was *supposed* to do — explicitly excluding any mention of bugs, since I wanted to build my own mental model and find the issues myself. I read all of this myself before starting Milestone 2. Claude also drafted the initial Codebase Map (file roles, the add-to-playlist data flow trace, and the "patterns noticed" section) in `submission.md`, which I reviewed against the actual code.

**Reproducing bugs (Milestone 2):** For each issue, I asked Claude to help me trigger the bug through the *real* app (live routes), not just by reasoning about the code. This mattered most for Issue #1: the streak bug only manifests on a Saturday→Sunday transition, and the live app always uses the real system clock, so Claude used Flask's `test_client()` combined with monkey-patching `datetime.now()` in a throwaway script (no source files touched) to fire real HTTP-shaped requests while controlling the date. For Issues #2, #4, and #5, reproduction was simpler — real API calls against seeded users, comparing before/after state (notification counts, feed contents, playlist song counts).

**Root cause tracing (Milestone 3):** For each bug, I had Claude walk the code path and compare it against the function's own docstring or a working sibling function, rather than guess. This surfaced two recurring patterns: a docstring/code mismatch (Issues #1 and #5, where the documented behavior directly contradicted a specific line of code — an extra `weekday() != 6` clause and a `[:-1]` slice, respectively) and a missing architectural step (Issue #4, where `rate_song()` was missing an entire notify-the-sharer block that its sibling `add_to_playlist()` had). I verified each proposed root cause myself by reading the flagged line before accepting it.

**Where I pushed back / verified independently:** After the Issue #2 fix (changing `RECENT_THRESHOLD` from 24 hours to 30 minutes), I didn't accept the diff at face value — I asked whether it had actually been tested, since changing a keyword argument name/value alone doesn't prove functional correctness. Claude re-ran the live endpoint against fresh seed data and showed the actual before/after counts, which is when I accepted the fix. I also required explicit test-suite runs and live endpoint re-checks after every fix, not just a code diff, before considering any bug closed.

**Issue #3 (search duplicates) — the case where AI's investigation didn't reach a clean answer:** Claude found a genuine bug in `search_songs()` (an unnecessary `outerjoin` to `song_tags` that fans out rows per tag), and proved the underlying row duplication exists using raw `sqlite3` and SQLAlchemy's Core `select()` API. But it could not get the bug to surface through the actual app code path (`search_songs()` itself, the live endpoint, or the project's own test suite) — it determined the installed SQLAlchemy version (2.0.51) appears to auto-deduplicate legacy `Query.all()` results regardless of relationship configuration, even for an unrelated bare model with no relationships at all. This was a case where the AI's investigation was thorough but inconclusive for a live reproduction; I made the final call myself to not count this bug toward the submission (documented as an investigated-but-unfixed entry) rather than have Claude force a workaround or fabricate a reproduction that didn't reflect real app behavior.

**Commit hygiene:** I did all `git add`/`git commit` steps myself rather than having Claude run them, so I stayed in control of what got committed and when. Claude flagged that my first commit (the Issue #1 fix) didn't follow the required `fix:` conventional-commit prefix. I initially decided to leave it as-is, then changed my mind and had it reworded via a non-interactive rebase (cherry-pick replay, since the interactive `rebase -i` editor isn't available in this environment) followed by a force-push to my fork, since that commit was already pushed. A backup branch was created first, and the rewritten tree was diffed against the original to confirm the content was byte-for-byte identical — only that one commit message actually changed.

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

4 of 5 issues fixed and documented below (#1, #2, #4, #5) — exceeding the 3-required minimum and one short of all 5. Issue #3 was investigated thoroughly but is not counted toward this submission; see its entry below for why.

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

### Issue #3 — The same song keeps showing up twice in search (investigated, not fixed — not counted toward this submission)

**How I attempted to reproduce it:**

`search_songs()` does an unnecessary `outerjoin` to `song_tags` (a many-to-many association table) but never actually filters/selects on tag data — only `title`/`artist`. Confirmed at the raw `sqlite3` level (bypassing the ORM) that this join genuinely fans out: for a 3-tag song ("Crown Heights Anthem"), it produces 3 duplicate rows.

However, through the actual app code path — `db.session.query(Song).outerjoin(...).all()`, which is exactly what `search_songs()` runs — the duplication does not currently surface. Verified this several ways, all deduplicated to a single result: calling `search_songs()` directly, hitting the real `GET /songs/search` endpoint, running the project's own `pytest tests/test_search.py` (all 5 tests pass), an unrelated sanity check joining `User` to `ListeningEvent`, and even a completely bare SQLAlchemy model (no Flask-SQLAlchemy, no relationships at all) mapped directly onto the `song` table — still deduplicated. The only way the raw fan-out actually surfaces is via SQLAlchemy 2.0's Core-style `select()` + `session.execute()` *without* calling `.unique()` on the result (confirmed: 3 rows).

**Conclusion:** the underlying bug is real — an unnecessary join that fans out per tag row — but the installed SQLAlchemy version (2.0.51) appears to universally auto-deduplicate full-entity results for the legacy `Query.all()` API this codebase uses, regardless of relationship/eager-loading configuration. That means the reported symptom doesn't currently surface through any real user-facing path in this environment.

**Status:** parked — not reproduced through the live app, not fixed, not counted toward this submission. Treating this as a 4-of-5 submission (#1, #2, #4, #5 fixed and documented); this entry is kept as a record of the investigation in case it's revisited later.

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

Read `get_playlist_songs()` in `services/playlist_service.py` top to bottom. The query (joining `Song` to `playlist_entries`, filtering by playlist, ordering by `position`) correctly builds the full, ordered list — nothing wrong there. The `return` statement right below it is `[song.to_dict() for song in songs[:-1]]`. The function's own docstring includes a `Note:` explicitly stating "This function returns all songs in the playlist" — directly contradicted by the `[:-1]` slice on the very next meaningful line. That contradiction between the documented behavior and the actual return statement was the confirming moment, same pattern as Issue #1's docstring-vs-code mismatch.

**The root cause:**

The query fetches every song in the playlist, correctly ordered by position. But the list comprehension slices the result with `songs[:-1]` before returning, which drops the last element of any non-empty list — i.e., the song at the highest position, regardless of how many songs are in the playlist. `test_empty_playlist_returns_empty_list` didn't catch this because `[][:-1] == []`, so the bug is invisible for empty playlists and only manifests once a playlist actually has songs.

**Fix and side-effect check:**

Removed the `[:-1]` slice, returning `[song.to_dict() for song in songs]`. Checked callers: `get_playlist_songs()` is called from `routes/playlists.py`'s `GET /playlists/<id>/songs` route (the real usage) and is also imported — but never actually called — inside `notification_service.add_to_playlist()` (a pre-existing dead import, unrelated to this fix). Ran the full test suite: all 13 tests now pass, including the two in `test_playlists.py` that were previously failing (`test_playlist_returns_all_songs`, `test_playlist_returns_songs_in_order`); `test_empty_playlist_returns_empty_list` still passes, confirming the empty-playlist boundary still works correctly. Re-ran the original reproduction against the live API: "Late Night Vibes" now correctly returns all 7 songs, including the previously-missing "Free Throws" at position 7.

---

## git log Screenshot

![git log --oneline output](/GitLog_Screenshot.png)

```
a085664 docs: write AI usage section and finalize submission for Milestone 4
6fa8562 docs: document Issue #3 investigation and final 4-of-5 scope decision
e4db7b1 fix: return the last song in a playlist instead of dropping it
d418501 fix: send notification when a song is rated, matching the add-to-playlist pattern
8113dc3 fix: tighten friends-listening-now threshold from 24 hours to 30 minutes
0a6fc19 fix: remove erroneous Sunday exception in streak increment logic
7ec36f9 done with milestone 2
9dacbba .
2dfdeaa Add .gitignore file and update README with setup instructions
7b64551 initial commit
```

All 4 bug-fix commits (`0a6fc19`, `8113dc3`, `d418501`, `e4db7b1`) follow the `fix:` convention.
