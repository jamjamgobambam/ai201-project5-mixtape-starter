# Mixtape Bug Hunt — Submission

## AI Usage

*(Written at the end — see the "AI Usage" section at the bottom for the full account. Placeholder here so the required section is easy to find.)*

I used Claude Code (Opus 4.8) as a navigation and tracing partner throughout this project. Specifics — including where its output was correct, where I verified it myself, and one place where the "obvious" bug did not actually reproduce — are documented in the **AI Usage (detailed)** section at the end of this file and inline in each root-cause analysis entry.

---

## Codebase Map

Mixtape is a Flask app organized in three layers: **models → services → routes**. Every route does only input parsing and response formatting; all business logic lives in a service function. This is the single most important structural pattern — if an endpoint misbehaves, the cause is almost always in the service it calls, not the route.

### Main files and their roles

- **`app.py`** — Flask application factory (`create_app`) and the shared `SQLAlchemy` instance (`db`). Registers four blueprints under URL prefixes: `/songs`, `/playlists`, `/users`, `/feed`. Calls `db.create_all()` inside an app context. Note: run with `flask run` (env `FLASK_APP=app:create_app`), **not** `python app.py`, to avoid a double-import of the models.

- **`models.py`** — Defines the data model as SQLAlchemy models plus three association tables:
  - **Entities:** `User`, `Tag`, `Song`, `ListeningEvent`, `Rating`, `Playlist`, `Notification`.
  - **Association tables:** `friendships` (symmetric many-to-many self-join on `User`), `song_tags` (many-to-many `Song`↔`Tag`), and `playlist_entries` (many-to-many `Playlist`↔`Song` **with extra columns** `position`, `added_by`, `added_at`). `playlist_entries.position` is what gives songs an explicit order rather than insertion order.
  - Ratings are their own `Rating` model (not a column on `Song`), with a `UniqueConstraint(user_id, song_id)` so a user can rate a song only once.
  - All timestamps default to timezone-aware UTC (`datetime.now(timezone.utc)`).

- **`services/streak_service.py`** — Listening-streak logic. `record_listening_event()` writes a `ListeningEvent` and calls `update_listening_streak()`, which compares `today` to the user's `last_listened_at.date()` and increments / holds / resets the streak. `get_streak()` reads the stored value.

- **`services/feed_service.py`** — `get_friends_listening_now()` returns friends who listened within `RECENT_THRESHOLD`, deduped to the most recent song per friend. `get_activity_feed()` returns the most recent N friend events regardless of recency.

- **`services/search_service.py`** — `search_songs()` matches `Song.title`/`Song.artist` against a query (case-insensitive `ilike`). `get_song()` fetches one song by id.

- **`services/notification_service.py`** — Creates and reads `Notification` records. `create_notification()` is the shared writer. `add_to_playlist()` adds a song to a playlist **and** notifies the song's original sharer. `rate_song()` upserts a `Rating`. `get_notifications()` / `mark_as_read()` are the read side.

- **`services/playlist_service.py`** — `create_playlist()`, `get_playlist_songs()` (ordered by `playlist_entries.position`), `get_playlist()` (metadata only), `get_user_playlists()`.

- **`routes/*.py`** — Thin HTTP wrappers. `songs.py` (search, detail, rate, listen), `playlists.py` (create, detail, list songs, add song), `users.py` (profile, streak, notifications, mark-read), `feed.py` (listening-now, activity). Each catches `ValueError` from the service and maps it to a 404/400 JSON error.

- **`seed_data.py`** — Drops and recreates the DB, then seeds 5 users with friendships, 25 songs deliberately spanning **0, 1, and 3+ tags** (to exercise the search-dedup case), 3 playlists, recent + old listening events, streak state, and one existing "song added to playlist" notification (so the working notification pattern is visible when investigating Issue #4).

- **`tests/`** — `test_streaks.py`, `test_search.py`, `test_playlists.py`. Several tests are written to fail against the seeded bugs and pass once fixed.

### Data flow trace — "a friend adds my song to a playlist and I get notified"

1. `POST /playlists/<playlist_id>/songs` with JSON `{song_id, added_by}` → `routes/playlists.py::add_song()`.
2. The route validates the two fields and calls `notification_service.add_to_playlist(playlist_id, song_id, added_by)`.
3. `add_to_playlist()` loads the `Song`, the adding `User`, and the `Playlist` (raising `ValueError` if any is missing — which the route turns into a 400/404).
4. If the song is not already in `playlist.songs`, it appends it and commits (this insert into `playlist_entries` is what makes the song a playlist member).
5. **If the adder is not the original sharer** (`song.shared_by != added_by_user_id`), it calls `create_notification(user_id=song.shared_by, type="song_added_to_playlist", body=...)`, which inserts a `Notification` row and commits.
6. Later, the sharer polls `GET /users/<user_id>/notifications` → `routes/users.py::notifications()` → `notification_service.get_notifications()`, which returns their notifications newest-first.

This is the reference pattern for Issue #4: the *rating* path (`rate_song`) is supposed to mirror step 5 but doesn't.

### Patterns worth noting

- **Route → service delegation** everywhere; services raise `ValueError` for "not found," routes translate to HTTP status codes.
- **UTC everywhere**, but `last_listened_at` can come back from SQLite as naive, so `update_listening_streak` re-attaches `tzinfo=utc` before comparing.
- **Association tables carry data** (`playlist_entries.position`), so ordering/paging bugs tend to live in how those columns are queried.
- **Legacy `db.session.query(Entity)`** is used throughout. This detail matters for Issue #3: the legacy ORM `Query` de-duplicates full entities by primary key, which masks the join-fan-out duplicate in this SQLAlchemy 2.0 environment.

---

## Bugs I plan to fix

Required three: **#1 streak reset**, **#5 last playlist song**, **#4 rating notification**.
Stretch: **#2 "listening now" window**.
Issue #3 is documented as a *latent* bug that does not reproduce under the current SQLAlchemy version (see notes below).

---

## Root Cause Analysis

### Issue #1 — My listening streak keeps resetting

**How I reproduced it.** Ran the existing suite: `pytest tests/test_streaks.py::test_streak_increments_on_sunday` fails with `assert 1 == 2`. The test listens on Saturday (`weekday() == 5`) then Sunday (`weekday() == 6`); the streak should go 1 → 2 but instead reset to 1. This isolates the bug to a Sunday boundary with no HTTP round-trip needed.

**How I found the root cause.** The affected service was named in the issue table (`streak_service.py`). I read `update_listening_streak()` top-to-bottom and traced the day-difference branch. `days_since_last` was computed correctly (Sat→Sun is 1 day), so the increment branch *should* have run. The moment of certainty was seeing the branch condition `days_since_last == 1 and today.weekday() != 6` — the second clause has nothing to do with consecutive-day logic, and `6` is exactly Sunday's `weekday()` value. That made the failing Sunday case fall through to the `else` reset.

**The root cause.** Python's `datetime.weekday()` returns `6` for Sunday. The streak-increment branch required `days_since_last == 1 AND today.weekday() != 6`. On any Sunday, `today.weekday() != 6` is `False`, so a user who listened the previous day did **not** hit the increment branch and instead fell to the `else`, which resets the streak to 1. The consecutive-day check (`days_since_last == 1`) was already correct on its own; the weekday clause was a spurious extra condition that only ever broke Sundays.

**My fix and side-effect check.** Removed the `and today.weekday() != 6` clause so the branch is simply `elif days_since_last == 1:`. I re-ran the full `test_streaks.py`: all 5 pass, including `test_streak_resets_after_skipped_day` (the `else` reset still fires when a day is genuinely skipped) and `test_streak_does_not_double_count_same_day`. So both sides of the boundary — legitimate increment and legitimate reset — still behave correctly.

*AI note: Claude confirmed via the failing test which weekday value maps to Sunday and pointed at the suspicious clause; I verified the `weekday()==6` mapping and the branch fall-through myself by reading the code.*

### Issue #5 — The last song in a playlist never shows up

**How I reproduced it.** `pytest tests/test_playlists.py` — `test_playlist_returns_all_songs` fails returning 4 songs for a 5-song playlist, and `test_playlist_returns_songs_in_order` fails because `"Track 5"` (the last, highest-position song) is missing from the ordered result. Because the query orders by `position` ascending, the *last* song is always the one dropped.

**How I found the root cause.** Opened `playlist_service.py::get_playlist_songs()`. The SQL query itself was clearly correct — it joins `playlist_entries`, filters by playlist, and orders by `position` ascending, and the docstring explicitly promises "all songs." I read the query result into `songs` and then looked at the single return line. The certainty moment was the slice `songs[:-1]` in the list comprehension: `[:-1]` drops the final element, so exactly one song — always the last by position — is silently removed after a fully-correct query.

**The root cause.** The return statement was `return [song.to_dict() for song in songs[:-1]]`. The `[:-1]` slice excludes the last item of the ordered list. Since the list is ordered by playlist position ascending, the excluded item is always the last song in the playlist. The data layer and query were correct; the truncation happened purely in the Python return expression — a classic off-by-one.

**My fix and side-effect check.** Changed the slice to iterate the full list: `for song in songs`. Re-ran `test_playlists.py`: all 3 pass. I specifically checked the empty-playlist path (`test_empty_playlist_returns_empty_list`) since a slice edge case could have hidden there — an empty query returns `[]` and iterating it still returns `[]`, so no regression. Ordering is untouched because the `order_by(position)` in the query is unchanged.

*AI note: entirely a read-the-code find; AI's role was only to run the test suite and surface the failing count. The `[:-1]` diagnosis is self-evident on inspection.*

### Issue #4 — I got notified when a friend added my song to a playlist but not when they rated it

**How I reproduced it.** No existing test covers this, so I wrote a small `flask shell`-style script against the seeded DB: pick a song shared by `simone`, have `nova` (a different user) rate it via `rate_song()`, then read `get_notifications(simone.id)` before and after. Result: the sharer's notification count stayed at `0` after the rating, and no `song_rated` notification type was ever present. For contrast, the seed data already contains a working `song_added_to_playlist` notification, and `add_to_playlist()` visibly creates one — so the playlist path notifies and the rating path does not.

**How I found the root cause.** The issue names `notification_service.py`, which contains both the working path (`add_to_playlist`) and the broken one (`rate_song`). Per the brief's hint that the cause is architectural, not a typo, I read the two functions line-by-line side by side. `add_to_playlist` performs its action, then guards `if song.shared_by != added_by_user_id:` and calls `create_notification(...)`. `rate_song` performs its action (upsert the `Rating`), commits, and returns — with **no** `create_notification` call anywhere. The moment of certainty was confirming the entire notify block is simply absent from `rate_song`; it's a missing step, not a broken comparison.

**The root cause.** `rate_song()` saves the rating and returns without ever creating a `Notification` for the song's original sharer. The notification system is driven entirely by explicit `create_notification()` calls inside each service action; the rating action was never given one. So a rating is persisted correctly but produces no side-effect notification, unlike every other sharer-facing interaction.

**My fix and side-effect check.** I mirrored the `add_to_playlist` pattern: after committing the rating, if the rater is not the sharer (`song.shared_by != user_id`), create a `song_rated` notification addressed to `song.shared_by`. I added an `is_new_rating` flag so the notification only fires when a *new* `Rating` row is created, not when an existing rating's score is updated (re-rating shouldn't spam the sharer). Verified three cases against the seeded DB: (1) a non-sharer rating creates exactly one `song_rated` notification with a correct body; (2) re-rating the same song leaves the count unchanged; (3) the sharer rating their own song creates no notification. The full test suite (13 tests) still passes, so the rating upsert and unique-constraint behavior are unaffected.

*Separate observation (not one of the five issues): `add_to_playlist` crashes with a `NOT NULL constraint failed: playlist_entries.position` when adding a genuinely new song, because `playlist.songs.append(song)` doesn't populate the association-table's `position`/`added_by` columns. I noticed this while building the reproduction and deliberately scoped my #4 repro to the rating path so as not to conflate the two. Left unfixed since it's outside the assigned bug list.*

*AI note: Claude wrote the reproduction script and ran the three-case verification; I confirmed the missing `create_notification` call by reading both functions and decided the re-rating de-dup behavior myself.*

### Issue #2 — Friends Listening Now shows people from yesterday *(stretch)*

**How I reproduced it.** Re-seeded the DB and called `get_friends_listening_now()` for `darius`, printing each returned friend's most-recent listen age. Result: it returned **simone (15 min ago)** *and* **nova (120 min / 2 h ago)**. nova had not listened recently at all — her most recent event was 2 hours old — yet she appeared in "Listening Now." That's the reported "people from yesterday" symptom: stale listeners treated as currently active. (I used `darius` as the current user specifically because he has a friend, nova, whose only events are hours old; for `nova` herself all three friends happen to have sub-30-minute events, so the bug is invisible from her vantage point — a good reminder to pick reproduction state deliberately.)

**How I found the root cause.** The issue names `feed_service.py`. `get_friends_listening_now()` computes `cutoff = now - RECENT_THRESHOLD` and filters `ListeningEvent.listened_at >= cutoff`. The query and the per-friend dedup were both correct. The only thing that determines "how recent is recent" is the module constant `RECENT_THRESHOLD`, defined at the top as `timedelta(hours=24)`. Cross-checking against `seed_data.py`, whose comments explicitly say recent events are "within the past 30 minutes — should appear" and older ones "should NOT appear after fix," confirmed the threshold was simply set an order of magnitude too wide.

**The root cause.** `RECENT_THRESHOLD` was `timedelta(hours=24)`. "Friends Listening Now" is meant to show who is listening *right now*, but a 24-hour window includes anyone who listened at any point in the last full day. So a friend who listened hours ago — or last night — is reported as currently listening. The logic around it (cutoff subtraction, filter, most-recent-per-friend dedup) was all correct; only the window size was wrong.

**My fix and side-effect check.** Changed `RECENT_THRESHOLD` to `timedelta(minutes=30)`, matching the "now" semantics and the seed data's stated 30-minute recency band. Verified both sides of the boundary: simone (15 min) still appears, nova (2 h) is now excluded. I also checked `get_activity_feed()`, which deliberately does **not** filter by recency (its docstring says so) — it still returns the older events for both friends, confirming I only narrowed the "listening now" window and didn't affect the general activity feed. Full test suite still passes (13/13).

*AI note: Claude ran the reproduction and identified that all of nova's friends have recent events (masking the bug from her perspective), which is why we reproduced from darius's account instead. I verified the 30-minute intent against the seed data comments myself rather than taking the number on faith.*

---

## Regression Tests

Bugs #1 and #5 already had tests in the repo that failed against the seeded bugs (`test_streak_increments_on_sunday`, `test_playlist_returns_all_songs`, `test_playlist_returns_songs_in_order`) and pass after the fixes. For the two bugs that had **no** existing coverage, I added regression tests:

- **`tests/test_notifications.py`** (Issue #4) — `test_rating_notifies_the_sharer` asserts that a rating by a non-sharer creates exactly one `song_rated` notification for the sharer; plus `test_rerating_does_not_duplicate_notification` and `test_rating_own_song_does_not_notify` pin the edge behavior.
- **`tests/test_feed.py`** (Issue #2) — `test_listening_now_excludes_stale_listener` sets up a friend who listened 5 minutes ago and one who listened 3 hours ago, and asserts only the recent friend appears in "Listening Now."

I verified these are *real* regression tests by temporarily reverting both fixes (restoring the 24-hour threshold and removing the rating-notification block): the two new tests fail (`assert 0 == 1`, stale friend present), then pass again once the fixes are restored. Full suite is **17 passing**.

```
pytest tests/          # 17 passed
```

---

## Note on the git log screenshot

Commits are being made manually (one per fix, `fix:` conventional format, on `bugfix/mixtape`). After committing, capture `git log --oneline` and paste the screenshot here. Suggested commit messages:

- `fix: remove spurious Sunday guard in streak increment logic` (Issue #1 — `services/streak_service.py`)
- `fix: return all playlist songs instead of dropping the last one` (Issue #5 — `services/playlist_service.py`)
- `fix: notify song sharer when a friend rates their song` (Issue #4 — `services/notification_service.py`)
- `fix: narrow 'listening now' window from 24h to 30m` (Issue #2 — `services/feed_service.py`)
- (optional) `test: add regression tests for rating notifications and listening-now window`

---

## AI Usage (detailed)

I used Claude Code (Opus 4.8) as a pair-debugging partner. Concretely:

**Codebase orientation.** I had Claude read `models.py` and every file in `services/` and `routes/` and summarize each module's responsibility and the route→service→model call chains. This is what the codebase map above is built from. I cross-checked the map against the files myself — in particular the association-table detail (`playlist_entries.position`), which is the kind of thing a summary can gloss over but turned out to matter for two bugs.

**Reproduction.** Claude wrote the throwaway scripts that reproduced Issues #4 and #2 against the seeded DB (the ones without existing tests), and ran the existing pytest suite to reproduce #1 and #5. For #2 it caught something I would have missed: the bug is invisible if you reproduce from `nova`'s account because all her friends have recent events — so we reproduced from `darius` instead. I decided which user/state to test based on that.

**Where AI was right, and where I verified.** The `datetime.weekday()==6 == Sunday` mapping (#1) and the `[:-1]` slice (#5) were things Claude flagged and I confirmed by reading the code and the failing tests. For #4 I confirmed the missing `create_notification` call myself by reading `add_to_playlist` and `rate_song` side by side, and I chose the re-rating de-dup behavior (only notify on a new rating) rather than taking a default. For #2 I verified the 30-minute window against `seed_data.py`'s own comments rather than trusting a guessed number.

**Where the "obvious" AI answer was wrong.** Issue #3 (search duplicates) is the clearest example. The naive expectation — and what an AI would confidently tell you — is that the `outerjoin(song_tags)` fans out one row per tag and duplicates multi-tag songs. But when I actually ran `search_songs()` against the seed data and the existing `test_search_no_duplicates_multi_tag_song` test, there were **no duplicates**: SQLAlchemy 2.0's legacy `db.session.query(Entity)` de-duplicates full entities by primary key, so the fan-out is collapsed before it reaches the caller. The bug is latent (it would resurface under a 2.0-style `select()`), but it does not reproduce as written — so I did not count it toward the required three and documented why. This is the case where reading and *running* the code beat the plausible-sounding explanation.

**Also surfaced by AI, out of scope.** While reproducing #4, the reproduction hit a real `NOT NULL constraint failed: playlist_entries.position` in `add_to_playlist` (appending to `playlist.songs` doesn't set the association-table's required columns). It's a genuine bug but not one of the five assigned issues, so I noted it and left it unfixed.
