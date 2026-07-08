# Project 5 — Mixtape Bug Hunt — Submission

## Codebase Map

Mixtape is a Flask app using an application-factory pattern. Every HTTP route is thin:
it parses input and formats the JSON response, then delegates all business logic to a
service function. All the bugs live in the `services/` layer.

### Main files and their roles

- **`app.py`** — Flask application factory (`create_app`). Instantiates the shared
  `SQLAlchemy` object `db`, configures the SQLite database URI, registers the four route
  blueprints under URL prefixes (`/songs`, `/playlists`, `/users`, `/feed`), and calls
  `db.create_all()`. The app must be started with `FLASK_APP=app:create_app flask run`;
  running `python app.py` triggers a double-import of the models.

- **`models.py`** — Defines the data model with 6 SQLAlchemy models and 3 association
  tables:
  - `User` — has `listening_streak` (int) and `last_listened_at` (datetime) columns used
    by the streak feature; a self-referential many-to-many `friends` relationship via the
    `friendships` table.
  - `Song` — shared by a user (`shared_by` FK); many-to-many `tags` via `song_tags`.
  - `Tag` — song genre/mood labels.
  - `ListeningEvent` — one row per play, with `user_id`, `song_id`, `listened_at`.
  - `Rating` — a user's 1–5 score for a song, with a unique `(user_id, song_id)`
    constraint (one rating per user per song). The rating is its own model, not a column
    on `Song`.
  - `Playlist` — many-to-many `songs` via the **`playlist_entries`** association table,
    which carries extra columns: `position` (explicit ordering), `added_by`, `added_at`.
    So playlist membership has an explicit position, not just insertion order.
  - `Notification` — `user_id` (recipient), `notification_type`, `body`, `read`.

- **`routes/`** — one blueprint per resource. Each endpoint does input parsing + response
  formatting only, then calls a service and translates `ValueError` into an HTTP error.
  - `songs.py` — `/songs/search`, `/songs/<id>`, `/songs/<id>/rate`, `/songs/<id>/listen`
  - `playlists.py` — playlist CRUD + `/playlists/<id>/songs`
  - `users.py` — `/users/<id>`, `/users/<id>/streak`, `/users/<id>/notifications`
  - `feed.py` — `/feed/<id>/listening-now`, `/feed/<id>/activity`

- **`services/`** — all business logic: `streak_service`, `feed_service`,
  `search_service`, `notification_service`, `playlist_service`.

- **`seed_data.py`** — drops and recreates the DB, then seeds 5 users (nova, darius,
  simone, kenji, aaliya) with friendships, 13 songs across 0/1/3-tag buckets, 3 playlists,
  listening events (recent + old), streaks, and one working playlist-add notification.

- **`tests/`** — pytest suites for streaks, search, and playlists. Each uses an in-memory
  SQLite DB. Several tests already encode the *expected* (post-fix) behavior and fail
  against the buggy code — they double as regression tests.

### Data flow — recording a listen and updating a streak (Issue #1's feature)

1. `POST /songs/<song_id>/listen` with `{"user_id": ...}` hits `listen()` in
   [routes/songs.py](routes/songs.py).
2. The route calls `record_listening_event(user_id, song_id)` in
   [services/streak_service.py](services/streak_service.py).
3. That function loads the `User`, creates a `ListeningEvent` row stamped with `now`
   (UTC), then calls `update_listening_streak(user, now)`.
4. `update_listening_streak` compares `now.date()` against `user.last_listened_at.date()`:
   same day → no change; exactly 1 day later → increment; otherwise → reset to 1. It then
   updates `user.last_listened_at`.
5. `GET /users/<id>/streak` → `get_streak()` reads back `user.listening_streak`.

### Patterns I noticed

- **Route → service delegation everywhere.** No business logic lives in routes.
- **Services raise `ValueError`; routes catch it** and map to 400/404.
- **Time is UTC-based**, but stored SQLite datetimes are naive — services defensively
  re-attach `timezone.utc` (`last_listened.replace(tzinfo=timezone.utc)`).
- **Association tables carry data** (`playlist_entries.position`, `song_tags`), so joins
  through them can fan out rows — relevant to search/playlist bugs.

### AI usage disclosure

I used Claude Code to help navigate the unfamiliar codebase: summarizing each service
file's responsibility and tracing the route→service call chains. For each bug I formed the
hypothesis by reading the code myself, then verified it by reproducing the behavior with a
small script against a controlled in-memory database before editing. AI-assisted steps are
noted per-issue below.

---

## Root Cause Analysis

### Issue #1 — My listening streak keeps resetting

**How I reproduced it.** I isolated `update_listening_streak` in a script against an
in-memory DB, mirroring kenji's report: a user with `listening_streak = 12` whose
`last_listened_at` was a **Saturday** (`weekday() == 5`), then a listen on the following
**Sunday** (`weekday() == 6`). Saturday→Sunday is consecutive, so the streak should go to
13. Instead it dropped to **1**. Reproducing with a Monday→Tuesday pair worked fine, which
confirmed the bug was specific to Sundays — matching kenji's "both times it was a Sunday."

**How I found the root cause.** The README issue table pointed me straight at
`streak_service.py`. I read `record_listening_event` → `update_listening_streak` top-down.
The three-way date comparison (`days_since_last == 0 / == 1 / else`) is the correct shape,
but the middle branch had an extra, unexplained clause. I confirmed by printing
`today.weekday()` for the Sunday case: it was `6`, exactly the value the branch excluded.

**The root cause.** In [streak_service.py](services/streak_service.py) the increment branch
read:

```python
elif days_since_last == 1 and today.weekday() != 6:
    user.listening_streak += 1
else:
    user.listening_streak = 1
```

Python's `datetime.weekday()` returns `6` for Sunday. The `and today.weekday() != 6`
condition meant that when a consecutive-day listen happened to fall on a Sunday, the
`elif` evaluated to `False` even though `days_since_last == 1`. Execution fell through to
the `else`, which resets the streak to 1. Day-of-week is irrelevant to whether two listens
are on consecutive calendar days, so this clause was simply wrong — it silently discarded
the streak every Sunday.

**My fix and side-effect check.** I removed the spurious weekday clause so the branch is
purely `elif days_since_last == 1:`. I then verified both sides of the boundary:
- Saturday→Sunday (consecutive) now increments 12 → **13** ✅
- Friday→Sunday (a skipped Saturday) still resets to **1** ✅ — a genuinely skipped day
  landing on a Sunday is still correctly caught by the `else`.
- The full `tests/test_streaks.py` suite passes (5/5), covering new-user start-at-1,
  consecutive increment, same-day no-double-count, skipped-day reset, and the
  Sunday-increment regression test.

**AI usage.** I used Claude to confirm what `datetime.weekday()` returns for each day
(Monday=0 … Sunday=6) after I had already narrowed the bug to that comparison. The
diagnosis and fix were verified by reading the code and running the reproduction myself.
