# Project 5: Mixtape Bug Hunt — Submission

**Branch:** `bugfix/mixtape` · **Bugs fixed:** 5 of 5 · **Regression tests added:** 2 files (feed, notifications)

---

## AI Usage

I used an AI assistant (Claude) as a navigation and explanation partner, not as a
bug-finder-of-first-resort. The workflow was **I read the code → AI helped me
understand or confirm a mechanism → I verified the diagnosis by running the code
myself.**

Where AI genuinely helped:

- **Codebase orientation.** I had it summarize each `services/*.py` module and
  trace the route → service call chains (e.g. `POST /songs/<id>/rate` →
  `notification_service.rate_song`). This built the mental model in the codebase
  map below faster than reading cold.
- **Confirming a library behavior I was unsure about.** For Issue #3 I suspected
  the `outerjoin` produced duplicate rows, but the search test *passed*. I asked
  whether SQLAlchemy's legacy `Query.all()` uniquifies entities, then **verified
  it myself** in a REPL: the raw `select()` returns 3 rows for a 3-tag song while
  `db.session.query(Song)...all()` collapses them to 1. That verification changed
  how I wrote the root cause — the join is still wrong, but the visible symptom is
  masked in this SQLAlchemy version. I would not have caught that nuance if I'd
  trusted the AI's first "yes, that's your duplicate bug" answer.
- **Sanity-checking the streak fix.** I confirmed `datetime.weekday()` returns 6
  for Sunday (vs `isoweekday()` returning 7) before deciding the guard was bogus.

Where I had to override or verify independently:

- AI is confidently wrong when asked to *diagnose* before reading. Every actual
  root cause here came from reading the service file and reproducing the behavior
  first; the AI was useful for *explaining* code I'd already found.
- I reproduced all five bugs (failing tests or a REPL script) **before** editing,
  and re-ran the suite after each fix rather than trusting that a change "should"
  work.

---

## Codebase Map

*(Written during Milestone 1, before touching any bug.)*

Mixtape is a Flask app using SQLAlchemy over SQLite. It follows a strict
**route → service** layering: routes parse input and format JSON responses; all
business logic lives in `services/`.

### Main files and their roles

| File | Responsibility |
|------|---------------|
| `app.py` | Flask application factory (`create_app`). Configures the DB, registers the four blueprints under `/songs`, `/playlists`, `/users`, `/feed`, and calls `db.create_all()`. Owns the shared `db` object. |
| `models.py` | All SQLAlchemy models: `User`, `Tag`, `Song`, `ListeningEvent`, `Rating`, `Playlist`, `Notification`, plus three association tables (`friendships`, `song_tags`, `playlist_entries`). `playlist_entries` is a join table with an explicit `position` column — songs have an ordered place in a playlist, not just insertion order. |
| `seed_data.py` | Drops and recreates the DB with realistic fixtures: 5 users with friendships, 25 songs (deliberately including 0-, 1-, and 3+-tag songs to expose Issue #3), 3 playlists, recent + old listening events, and one working playlist-add notification (the reference pattern for Issue #4). |
| `routes/songs.py` | `GET /songs/search`, `GET /songs/<id>`, `POST /songs/<id>/rate`, `POST /songs/<id>/listen`. |
| `routes/playlists.py` | Create playlist, get metadata, `GET /playlists/<id>/songs`, add song. |
| `routes/users.py` | User profile, `GET /users/<id>/streak`, notifications list, mark-as-read. |
| `routes/feed.py` | `GET /feed/<id>/listening-now`, `GET /feed/<id>/activity`. |
| `services/streak_service.py` | Listening-streak rules (`update_listening_streak`). |
| `services/feed_service.py` | "Friends Listening Now" (recency-filtered) and the general activity feed. |
| `services/search_service.py` | Case-insensitive title/artist search. |
| `services/notification_service.py` | Create/retrieve notifications; `add_to_playlist` and `rate_song` are the two interaction entry points that *should* notify a song's sharer. |
| `services/playlist_service.py` | Playlist creation and ordered-song retrieval. |

### Data flow — rating a song (traced end to end)

`POST /songs/<song_id>/rate` (`routes/songs.py`) parses `user_id` and `score`,
casts the score to `int`, and calls
`notification_service.rate_song(user_id, song_id, score)`. That service validates
the score range (1–5), loads the `Song` and rater `User`, upserts a `Rating`
(unique per `(user_id, song_id)`), commits, and — after the fix — calls
`create_notification()` to notify `song.shared_by`. There is no separate rating
model beyond `Rating`; the notification is a side effect of the rate action, the
same way `add_to_playlist` notifies the sharer when a song is added to a playlist.

### Pattern noticed

Every route delegates immediately to a service function and does only I/O
concerns (parsing, status codes). This is why the README says "the bugs live in
the `services/` layer" — and all five did.

---

## Root Cause Analysis

### Issue #1 — My listening streak keeps resetting
*File: `services/streak_service.py` · Commit: `fix: increment listening streak on Sunday consecutive days`*

1. **Issue:** Users reported their listening streak resetting to 1 for no
   apparent reason.
2. **How I reproduced it:** The existing test `test_streak_increments_on_sunday`
   (Saturday → Sunday) failed: streak was 1, expected 2. That pinned the trigger
   to a Sunday-dated listen.
3. **How I found the root cause:** Read `update_listening_streak`. The increment
   branch was `elif days_since_last == 1 and today.weekday() != 6:`. I confirmed
   in a REPL that Python's `datetime.weekday()` returns **6 for Sunday**. So when
   the current listen fell on a Sunday, the increment condition was false even
   though exactly one day had passed, and control fell through to `else`, which
   resets the streak to 1.
4. **The root cause:** A spurious `today.weekday() != 6` guard. `weekday() == 6`
   is Sunday; the code treated every Sunday listen as if a day had been skipped,
   so any streak that crossed a Sunday boundary was wiped instead of incremented.
5. **My fix and side-effect check:** Removed the weekday guard, leaving
   `elif days_since_last == 1:`. A one-calendar-day gap now always increments,
   regardless of weekday. Side-effect check: re-ran all streak tests — new-user
   (start at 1), same-day (no double count), consecutive-day, and reset-after-gap
   all still pass. The reset behavior for genuine multi-day gaps is untouched
   because it lives in the `else`, which only the `days_since_last == 1` case ever
   bypassed.

### Issue #2 — Friends Listening Now shows people from yesterday
*File: `services/feed_service.py` · Commit: `fix: scope 'Friends Listening Now' to a 30-minute window`*

1. **Issue:** The "listening now" feed listed friends who hadn't listened in
   hours.
2. **How I reproduced it:** REPL script — one friend with a single
   `ListeningEvent` from 3 hours ago. `get_friends_listening_now` returned that
   friend (count 1) when a "now" feed should return 0.
3. **How I found the root cause:** Read `feed_service.py` top to bottom. The query
   filters `listened_at >= cutoff` where `cutoff = now - RECENT_THRESHOLD`, and
   `RECENT_THRESHOLD = timedelta(hours=24)`. `seed_data.py` confirmed intent: its
   comments split events into "within the past 30 minutes — should appear" and
   "1–14 days ago — should NOT appear."
4. **The root cause:** The recency window was 24 hours, not the ~30 minutes that
   "listening *now*" implies. Anyone who listened in the last day qualified.
5. **My fix and side-effect check:** Changed `RECENT_THRESHOLD` to
   `timedelta(minutes=30)`. Verified both sides of the boundary with a new test
   file `tests/test_feed.py`: a 10-minute-old and a 29-minute-old listen appear; a
   3-hour-old listen does not. `get_activity_feed` is intentionally *not*
   recency-filtered (per its docstring) and was left unchanged.

### Issue #3 — The same song keeps showing up twice in search
*File: `services/search_service.py` · Commit: `fix: remove tag outerjoin that duplicated multi-tag songs in search`*

1. **Issue:** Search returned the same song multiple times.
2. **How I reproduced it:** The search test suite passed unexpectedly, so I
   reproduced at the SQL level in a REPL: the buggy query's underlying
   `select()` returned **3 rows** for a 3-tag song, while the ORM
   `db.session.query(Song)...all()` returned **1**.
3. **How I found the root cause:** Read `search_songs`. It does
   `.outerjoin(song_tags, Song.id == song_tags.c.song_id)` but never references
   `song_tags` in the `filter`. The join therefore fans the result out to one row
   per tag. I confirmed via the REPL that SQLAlchemy's *legacy* `Query.all()`
   auto-uniquifies whole entities by primary key, which is why the visible symptom
   is currently masked in this SQLAlchemy version.
4. **The root cause:** An unnecessary `outerjoin` against `song_tags`. It
   contributes nothing to filtering (search matches title/artist only) and
   multiplies rows by tag count. The correct duplicate-free behavior in this
   version happens only by accident of ORM entity-uniquing; the query is still
   wrong and would duplicate under `select()`/`.scalars()` execution or a
   `func.count`.
5. **My fix and side-effect check:** Dropped the join entirely (and the now-unused
   `Tag`/`song_tags` imports). Tags still populate correctly because `to_dict()`
   loads them via the `Song.tags` relationship (`lazy="subquery"`). Re-ran the
   search tests: single-tag, multi-tag, no-tag each return exactly one row, and
   no-match still returns `[]`.

### Issue #4 — Notified when a friend added my song to a playlist, but not when they rated it
*File: `services/notification_service.py` · Commit: `fix: notify song sharer when their song is rated`*

1. **Issue:** Rating a friend's song produced no notification, though adding a
   song to a playlist did.
2. **How I reproduced it:** REPL — user B rates user A's song, then
   `get_notifications(A)` returned 0 (expected 1).
3. **How I found the root cause:** Compared the two interaction handlers in the
   same file line by line, exactly as the brief's hint suggested. `add_to_playlist`
   ends with a `create_notification(user_id=song.shared_by, ...)` guarded by
   `if song.shared_by != added_by_user_id`. `rate_song` had no equivalent block —
   it persisted the `Rating` and returned.
4. **The root cause:** Architectural omission, not a typo. The notification side
   effect that every sharer-facing interaction is supposed to emit was simply
   missing from the rate path.
5. **My fix and side-effect check:** After the rating commit, added the same
   guarded `create_notification` call with `notification_type="song_rated"`,
   skipping self-ratings (`song.shared_by != user_id`). Added
   `tests/test_notifications.py`: rating another user's song notifies the sharer;
   rating your own song notifies no one; re-rating still routes to the sharer.
   The upsert/score-update logic is unchanged, so existing rating behavior is
   preserved.

### Issue #5 — The last song in a playlist never shows up
*File: `services/playlist_service.py` · Commit: `fix: include the last song when listing playlist songs`*

1. **Issue:** Every playlist was missing its final song.
2. **How I reproduced it:** The existing tests `test_playlist_returns_all_songs`
   (expected 5, got 4) and `test_playlist_returns_songs_in_order` (missing
   "Track 5") both failed.
3. **How I found the root cause:** Read `get_playlist_songs`. The query orders
   correctly by `position`, but the return statement is
   `return [song.to_dict() for song in songs[:-1]]`. The `[:-1]` slice discards
   the last element of the ordered list — the highest-position song.
4. **The root cause:** An off-by-one slice (`[:-1]`) on the ordered result,
   directly contradicting the function's own docstring ("returns all songs in the
   playlist").
5. **My fix and side-effect check:** Changed the slice to iterate the full list
   (`for song in songs`). Re-ran the playlist tests: all-songs count is 5, order
   is Track 1–5, and the empty-playlist case still returns `[]` (the old slice
   happened to return `[]` there too, so behavior on empty input is unchanged).

---

## Regression Tests

| Test file | Covers | Would have caught |
|-----------|--------|-------------------|
| `tests/test_streaks.py` (existing) | Issue #1 | `test_streak_increments_on_sunday` |
| `tests/test_search.py` (existing) | Issue #3 | duplicate-count assertions |
| `tests/test_playlists.py` (existing) | Issue #5 | count + order assertions |
| `tests/test_feed.py` (**added**) | Issue #2 | hours-old listen excluded; 29-min boundary included |
| `tests/test_notifications.py` (**added**) | Issue #4 | rating notifies sharer; self-rating does not |

Full suite after all fixes: **19 passed** (`pytest tests/`).
