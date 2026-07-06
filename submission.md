# Mixtape — Submission

## AI Usage

I used Claude throughout this project, and its role changed by phase:

**Codebase orientation (Milestone 1).** Gave Claude the full contents of `models.py`, every route file, every service file, `seed_data.py`, and the tests, and asked it to summarize each module's responsibility and trace specific data flows (rating a song, viewing a playlist, friends-listening-now). This is exactly the "file summary" / "data flow trace" pattern the assignment recommends. Output was checked against the README's own description of the app structure and the actual function bodies before being written into the codebase map — I didn't take the summary on faith.

**Explaining the 5 issues.** After orientation, I asked Claude to explain what was wrong in each of the 5 named service files. Claude had already read the code at that point (not guessing from the issue titles alone), and it pointed to specific lines — e.g., the `today.weekday() != 6` condition in `streak_service.py`, the missing `.distinct()` in `search_service.py`, the `songs[:-1]` slice in `playlist_service.py`. This matched the guidance to let AI explain code you've already found rather than asking it to diagnose blind.

**Reproduction and root cause (Milestones 2–3).** For each of the 3 chosen bugs (#1, #3, #5), the workflow was: trace the call chain by reading the route → service files myself/with Claude, form a specific hypothesis about the wrong line, then verify by execution rather than trusting the read-through. One real constraint shaped this phase: the sandbox environment Claude was running in has no PyPI/package-registry access, so the actual Flask + SQLAlchemy app couldn't be pip-installed and run there. To get real executed verification instead of just a code-reading argument, Claude isolated each buggy function's exact logic into standalone Python scripts with no external dependencies (copying the literal lines from the service file, mocking only the plain-attribute objects those lines touch) and ran them with concrete inputs drawn from the seed data and existing tests — e.g., a Saturday-then-Sunday pair of listen events for the streak bug, and the "Crown Heights Anthem" 3-tag song for the search bug. This is the same "isolate the function, call it directly, verify with a specific input" strategy the assignment describes for a Python REPL, just run as scripts instead of interactively.

Two places AI needed correction or double-checking rather than being trusted outright:
- When first asked to explain the streak bug, Claude's phrasing initially said the bug was "Sunday handling," which is the surface-level version the assignment explicitly warns against. I pushed for the exact comparison and expected-vs-actual return value, which produced the precise root cause below.
- The search and playlist fixes could not be confirmed against the real Flask/SQLAlchemy query engine in the AI's sandbox (network restrictions on the tooling side, not the app itself). Claude's logic-level Python reproduction demonstrates the same relational-algebra behavior (a join fans out rows; a slice drops the last element), but that is a model of the bug, not a run of the actual app. Running `pytest tests/ -v` locally, before and after each fix, is the authoritative confirmation and is still on me to do and record here. See each RCA entry's "reproduced/verified" note for exactly what was confirmed by script versus what still needs a local pytest run.

## Milestone 1: Codebase Map

### Main files and responsibilities

- **`app.py`** — Flask application factory (`create_app`). Owns the single `db = SQLAlchemy()` instance, loads config (DB URI, secret key), registers the four blueprints under their URL prefixes (`/songs`, `/playlists`, `/users`, `/feed`), and calls `db.create_all()`. `python app.py` is never used to start the app — that re-imports the module and causes a SQLAlchemy double-registration error. The app is started with `FLASK_APP=app:create_app flask run`.

- **`models.py`** — 6 SQLAlchemy models plus 3 association tables. Models: `User`, `Tag`, `Song`, `ListeningEvent`, `Rating`, `Playlist`, `Notification`. All primary keys are UUID strings generated via `generate_uuid()`, not autoincrement ints. Association tables:
  - `friendships` — self-referential, symmetric many-to-many on `User` (a friendship is inserted as two rows, one in each direction — see `seed_data.py`'s `add_friendship` helper).
  - `song_tags` — plain many-to-many between `Song` and `Tag`.
  - `playlist_entries` — many-to-many between `Playlist` and `Song`, but not a pure join table: it also carries `position` (explicit ordering, not insertion order), `added_by`, and `added_at`.
  Every model defines its own `to_dict()` for JSON serialization — there's no separate schema/serializer layer.

- **`routes/`** — thin controllers. Every route: parses the request (JSON body or query args), calls exactly one service function, and formats the response. `ValueError` raised by a service is caught and turned into a 404 (not-found) or 400 (bad input) JSON response. No business logic lives in routes.
  - `songs.py` — search, song detail, rate, listen.
  - `playlists.py` — create playlist, get playlist, get playlist songs, add song to playlist.
  - `users.py` — get user, get streak, get/mark notifications.
  - `feed.py` — friends listening now, activity feed.

- **`services/`** — all business logic.
  - `streak_service.py` — records listening events and updates `User.listening_streak` based on calendar-day gaps.
  - `feed_service.py` — "friends listening now" (last 24h, deduped to one song per friend) and a general activity feed (last N events, no recency filter).
  - `search_service.py` — title/artist substring search (case-insensitive), joined against `song_tags` to include tag data.
  - `notification_service.py` — creating/reading/marking-read `Notification` rows, plus (despite the module name) `add_to_playlist` and `rate_song`, which are really playlist- and rating-mutation logic that happen to also fire notifications.
  - `playlist_service.py` — create playlist, fetch playlist metadata, fetch a playlist's songs in position order.

- **`seed_data.py`** — populates the DB with 5 friended users, 25 songs (deliberately split into 0-tag / 1-tag / 3+-tag groups), 3 playlists, and a mix of recent (~10-25 min old) and older (2h-58h old) listening events. The comments in this file map directly to the 5 known issues (e.g. "should NOT appear in listening now after fix", "these are the ones that expose Issue #3") — it's built as a fixture for manually reproducing each bug, not just generic demo data.

- **`tests/`** — `test_streaks.py`, `test_search.py`, `test_playlists.py` already assert the *correct* behavior for issues #1, #3, and #5, with comments calling out the current buggy output (e.g. `assert len(songs) == 5  # Bug causes this to return 4`). No test files exist yet for issue #2 (feed) or #4 (notifications). Running `pytest tests/` is a fast way to confirm a fix without manual API calls.

### Data flow — rating a song

`POST /songs/<song_id>/rate` with JSON `{user_id, score}` →
`routes/songs.py::rate()` pulls `user_id`/`score` from the body, validates presence, casts `score` to `int` →
`services/notification_service.rate_song(user_id, song_id, score)`:
1. validates `1 <= score <= 5`
2. looks up the `Song` and the rating `User` (404 via `ValueError` if either is missing)
3. checks for an existing `Rating` for that `(user_id, song_id)` pair (enforced uniquely at the DB level too, via `UniqueConstraint`) — updates its `score` if found, otherwise creates a new `Rating`
4. commits and returns the `Rating`

Route wraps the result in `rating.to_dict()` and returns 201.

Notable: `rate_song` only ever touches the `Rating` table — it never calls `create_notification`. Compare with `add_to_playlist` in the same file, which does call `create_notification` after mutating `Playlist.songs`. Both functions live in `notification_service.py`, but only one of them actually creates a notification.

### Data flow — viewing a playlist's songs

`GET /playlists/<playlist_id>/songs` →
`routes/playlists.py::get_songs()` →
`services/playlist_service.get_playlist_songs(playlist_id)`:
1. looks up the `Playlist` (404 if missing)
2. queries `Song` joined to `playlist_entries` on `song_id`, filtered to this playlist, ordered ascending by `position`
3. maps each `Song` to `to_dict()` and returns the list

Route wraps this as `{"songs": [...], "count": N}`.

### Data flow — friends listening now

`GET /feed/<user_id>/listening-now` →
`routes/feed.py::listening_now()` →
`services/feed_service.get_friends_listening_now(user_id)`:
1. looks up the `User` (404 if missing)
2. computes `cutoff = now - 24h`, collects `friend_ids` from `user.friends` (the dynamic relationship backed by `friendships`)
3. queries `ListeningEvent` where `user_id in friend_ids` and `listened_at >= cutoff`, ordered most-recent-first
4. walks the results and keeps only the first (most recent) event per friend, so each friend appears at most once
5. returns a list of `{friend, song, listened_at}` dicts

### Patterns noticed

- **Routes → one service call → format response.** Consistent across all four route files. Makes it easy to trace any endpoint straight to its logic.
- **`ValueError` is the universal "not found / invalid input" signal** from services; routes never construct their own error JSON except for missing-body-field checks done before calling the service.
- **Module names don't always match responsibility.** `notification_service.py` contains rating and playlist-add logic, not just notification CRUD. When tracing a bug, the "obvious" file (e.g. a hypothetical `rating_service.py`) may not exist — the logic is filed under whichever feature happens to trigger a notification.
- **Timestamps are timezone-aware UTC by convention** (`default=lambda: datetime.now(timezone.utc)`), but `streak_service.update_listening_streak` defensively re-attaches `tzinfo=timezone.utc` to `user.last_listened_at` before comparing dates — implying naive datetimes can show up there in practice.
- **`playlist_entries` and `friendships` are "fat" association tables/relationships** — they carry ordering and directionality information beyond a simple many-to-many link, which matters for any code that reads or writes them directly (as `seed_data.py` and the tests do, via raw `.insert().values(...)` calls rather than ORM relationship methods).
- **Seed data and tests are pre-wired to the 5 known issues.** Both were clearly written by whoever staged this exercise specifically to make each bug reproducible and testable, rather than being generic sample data.

### Setup status

- Forked to `github.com/FahmidaAz/ai201-project5-mixtape-starter`, cloned locally.
- `bugfix/mixtape` branch created and checked out.
- Dependencies + `seed_data.py` to be run locally (see Setup section of README).
- App start command: `FLASK_APP=app:create_app flask run`, verified at `http://127.0.0.1:5000`.

### The five issues (read in full via README + project brief)

| # | Title | Affected service | Notes from orientation |
|---|-------|-------------------|--------------------------|
| 1 | Listening streak keeps resetting | `streak_service.py` | `test_streaks.py` already has a Sunday-specific test (`test_streak_increments_on_sunday`) — points at the day-of-week boundary logic in `update_listening_streak`. |
| 2 | "Friends Listening Now" shows people from yesterday | `feed_service.py` | `RECENT_THRESHOLD = timedelta(hours=24)` and the cutoff filter are the likely area; no test file yet for this one. |
| 3 | Same song shows up twice in search | `search_service.py` | `search_songs` joins `Song` to `song_tags` and doesn't deduplicate — a song with 3 tags would produce 3 joined rows. `test_search.py` confirms this exact shape (multi-tag song duplicates). |
| 4 | Notified on playlist-add but not on rating | `notification_service.py` | Confirmed above in the rate-a-song data flow: `add_to_playlist` calls `create_notification`, `rate_song` does not. |
| 5 | Last song in a playlist never shows up | `playlist_service.py` | `get_playlist_songs` slices the result with `songs[:-1]` before returning — the docstring says it "returns all songs" but the code drops the last one. `test_playlists.py` confirms (expects 5, bug returns 4). |

### Rough plan for which three to fix first

Based on orientation (not yet a diagnosis — fixes come in later milestones):

1. **Issue #5** (playlist) — smallest, most isolated fix, existing tests make verification immediate.
2. **Issue #1** (streak) — logic is self-contained in one function, existing Sunday test defines the exact expected fix.
3. **Issue #3** (search duplicates) — well-covered by tests, requires a slightly bigger query change (dedup or restructuring the join).

Issues #2 and #4 don't have dedicated tests yet, so they'd need test-writing as part of the fix — good candidates for the remaining two if time allows beyond the required three.

Chose to fix #5, #1, and #3, in that order, as planned above.

## Milestone 2 & 3: Reproduction and Root Cause Analysis

### Issue #1 — Listening streak keeps resetting

**How I reproduced it.** `update_listening_streak(user, now)` only reads and writes plain attributes on `user` (`listening_streak`, `last_listened_at`) — it doesn't touch the database directly — so I copied its exact logic (services/streak_service.py lines 56-78) into a standalone script with a mock user object and called it with two datetimes 24 hours apart: Saturday 2024-06-15 12:00 UTC, then Sunday 2024-06-16 12:00 UTC (the same pair used in `tests/test_streaks.py::test_streak_increments_on_sunday`). After the Saturday call the streak was 1 (correct). After the Sunday call — a real consecutive day — the streak stayed at 1 instead of advancing to 2. That reproduces "keeps resetting": it happens every week, on every Sunday, for any user who listened the day before.

**How I found the root cause.** Traced from the only caller, `record_listening_event`, into `update_listening_streak`. The docstring lists four rules — new user starts at 1, same-day is a no-op, consecutive day increments, skipped day resets — with no day-of-week exception mentioned anywhere. Reading the `if/elif/else` chain against those four rules, the line `elif days_since_last == 1 and today.weekday() != 6:` was the only place that didn't match a documented rule. I asked Claude to confirm what `datetime.weekday()` returns (0=Monday..6=Sunday, versus `isoweekday()` which is 1=Monday..7=Sunday) to make sure I had the right day identified before concluding the condition was the bug, then verified by running the isolated script with the Sat→Sun pair above.

**The root cause.** `update_listening_streak`'s increment branch requires both `days_since_last == 1` and `today.weekday() != 6`. `weekday() == 6` means the current day is Sunday. So whenever a user's second consecutive day of listening happens to fall on a Sunday, `days_since_last == 1` is true but the `and` condition is false as a whole, so the `elif` doesn't fire — control falls to the `else`, which unconditionally resets the streak to 1, exactly as if a day had been skipped. Nothing in the documented streak rules calls for a Sunday exception; the condition is simply an extra, incorrect clause that shouldn't be there.

**My fix and side-effect check.** Removed `and today.weekday() != 6`, leaving `elif days_since_last == 1:` so any consecutive day increments regardless of which weekday it is. Re-ran the isolated script against all 5 scenarios in `test_streaks.py` (new user → 1, consecutive day → increments, same day twice → no change, skipped day → resets to 1, Saturday→Sunday → increments) — all 5 now produce the expected value. Checked the only other functions in the file, `record_listening_event` (calls this function, unaffected structurally) and `get_streak` (just reads the stored value) — neither depends on the removed condition. **Still need to do:** run `pytest tests/test_streaks.py -v` locally to get the real Flask/SQLAlchemy-backed confirmation, since this fix was verified with an isolated copy of the logic, not the live app.

### Issue #3 — Same song shows up twice in search

**How I reproduced it.** `search_songs` performs `db.session.query(Song).outerjoin(song_tags, ...).filter(...).all()`. A SQL join produces one output row per matching pair on the joined table, independent of the database engine, so I modeled the join in plain Python using the seed data's "Crown Heights Anthem" song, which `seed_data.py` gives 3 tags (rap, hip-hop, boom bap) specifically, per its own comment, "to expose Issue #3." Simulating the outer join and filter for the query "Crown Heights" produced the song's title 3 times — matching `tests/test_search.py::test_search_no_duplicates_multi_tag_song`'s comment: "Should be 1, bug causes it to be 3."

**How I found the root cause.** Traced from `routes/songs.py::search()` to the only function it calls, `search_service.search_songs()`. The query joins `Song` to `song_tags`, but nothing in the function filters or selects by tag — tags are actually attached to each result afterward via `song.tags` inside `to_dict()`, a separate lazy-loaded relationship. That made the join itself suspicious: it has no purpose except to (accidentally) multiply rows. I asked Claude what edge cases could make this query return a wrong value, given the function; it named the join fan-out and the missing `.distinct()` as the specific mechanism, which I then confirmed independently by checking `seed_data.py`'s explicit 0-tag/1-tag/3-tag song groupings, built for exactly this scenario.

**The root cause.** `search_songs` joins `Song` to `song_tags` without filtering on or selecting any column from `song_tags`, and without a `.distinct()` call. An outer join to a table where a song can have many tag rows returns one joined row per tag, so a song's row is duplicated once per associated tag. A song with 0 tags returns once (outer join keeps it via a null tag row), 1 tag returns once, but 3 tags returns 3 times. `.all()` returns every one of those rows with no deduplication step.

**My fix and side-effect check.** Added `.distinct()` immediately before `.all()`, so SQLAlchemy deduplicates on the selected `Song` entity, collapsing the fanned-out rows back to one per distinct song while leaving the join, filter, and tag-loading logic untouched. Re-ran the logic-level reproduction for all 4 scenarios in `test_search.py` (0-tag, 1-tag, 3-tag, no-match) — the 3-tag song now returns once instead of 3 times, and the already-correct cases are unaffected. Checked `get_song`, the only other function in the file — it doesn't use this query at all, so it's unaffected. **Still need to do:** run `pytest tests/test_search.py -v` locally against the real database for authoritative confirmation.

### Issue #5 — Last song in a playlist never shows up

**How I reproduced it.** `get_playlist_songs` builds a correctly ordered list of songs and then returns `[song.to_dict() for song in songs[:-1]]`. I modeled the ordered list it would produce for the `seed_playlist` fixture in `tests/test_playlists.py` (5 songs at positions 1-5) and applied that exact final line — the output dropped "Track 5" and returned only 4 of the 5 songs, matching `test_playlist_returns_all_songs`'s comment: "Bug causes this to return 4."

**How I found the root cause.** Followed `GET /playlists/<id>/songs` from `routes/playlists.py::get_songs()` into `playlist_service.get_playlist_songs()`. The query (join on `playlist_entries`, filter by playlist id, order by `position`) looked correct on its own, so I compared the function against its own docstring, which states under "Note:" that "this function returns all songs in the playlist" — directly contradicted by the next line, `songs[:-1]`. That direct contradiction between the documented contract and the actual return statement was the point of confidence: the bug isn't in the query, it's a slice applied after the query already succeeded.

**The root cause.** The query in `get_playlist_songs` retrieves and orders every song in the playlist correctly. The final line, `return [song.to_dict() for song in songs[:-1]]`, uses Python's `[:-1]` slice, which drops the last element of any list. This happens unconditionally, regardless of playlist length or song positions — a playlist with 1 song returns an empty list, a playlist with 5 returns 4, and so on. It is a post-query bug, not a data-retrieval bug.

**My fix and side-effect check.** Changed `songs[:-1]` to `songs`, so every retrieved song is returned. Re-ran the logic-level reproduction (5 in, 5 out). Checked all 3 tests in `test_playlists.py`: `test_playlist_returns_all_songs` (expects 5 — now matches), `test_playlist_returns_songs_in_order` (expects exact position order — unaffected, since removing the slice doesn't change ordering), and `test_empty_playlist_returns_empty_list` (an empty list sliced or not is still empty — no regression). Checked `get_playlist` and `get_user_playlists`, the other two read functions in the file — neither calls `get_playlist_songs` or touches this code path. **Still need to do:** run `pytest tests/test_playlists.py -v` locally for authoritative confirmation.
