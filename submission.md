# Project 5: Mixtape Bug Hunt — Submission

**Branch:** `bugfix/mixtape`

Bugs fixed (3): **Issue #1** (streak resets on Sunday), **Issue #2** (Friends
Listening Now shows people from hours ago), **Issue #5** (last song in a playlist
never shows up).

---

## AI Usage

I used an AI coding assistant (Claude) throughout navigation, reproduction, and
debugging. What that actually looked like, honestly:

**Codebase orientation.** I had the assistant read each `services/` file and the
routes that call them and summarize the responsibility of each module and the
route → service call chain. This is where AI is strongest — it built the first
draft of the codebase map below quickly and accurately, because the code was
small enough to hold in full context. I verified every claim by reading the file
myself (e.g., confirming that `to_dict()` pulls tags via the `song.tags`
relationship, not the join in `search_songs`).

**Reproduction over guessing.** Before touching any code I ran the existing test
suite (`pytest tests/`) and a throwaway script that called each suspect service
function directly under an app context and printed what it returned. This is the
step where AI would have led me wrong if I'd trusted it blindly — see below.

**Where AI was wrong / incomplete — Issue #3.** The single most useful thing I
did was *not* believe the AI (or the seed-data comments, or the test docstrings)
about Issue #3. Every surface signal said the `outerjoin(song_tags)` in
`search_songs` would return a song with 3 tags three times. The AI agreed with
that reading. But when I actually ran `search_songs("Crown Heights")` and ran
`pytest tests/test_search.py`, the multi-tag song came back **exactly once** and
all search tests **passed**. The reason: SQLAlchemy's ORM deduplicates
full-entity query results by primary-key identity, so `query(Song).outerjoin(...)`
never yields duplicate `Song` objects even though the underlying SQL rows fan
out. The join is dead weight, but it is not an observable bug. Because I could
not reproduce Issue #3, I dropped it and picked a bug I *could* trigger, exactly
as the brief instructs. (This is documented more fully under "Issues investigated
but not fixed.")

**Where I used AI to confirm a diagnosis I'd already formed.** For Issue #1 I had
already narrowed the problem to the `today.weekday() != 6` guard; I asked the AI
to confirm the Python convention (`datetime.weekday()`: Monday=0 … Sunday=6, vs
`isoweekday()`: Monday=1 … Sunday=7) so my root-cause wording was precise. I
verified it in a REPL rather than taking its word.

The pattern that worked: **I** found the suspicious line by tracing route →
service and running the code; the **AI** explained mechanics and drafted prose;
**I** verified every diagnosis by running it with controlled inputs before
writing a fix. Asking the AI to "find the bug" cold (as with Issue #3) produced a
confident, plausible, wrong answer.

---

## Codebase Map

Mixtape is a small Flask + SQLAlchemy JSON API. Every HTTP route is a thin
wrapper that parses input, calls exactly one service function, and formats the
response; **all business logic lives in `services/`**. That is the dominant
architectural pattern — the routes never touch the ORM directly except
`routes/users.py`'s trivial `get_user` lookup.

### Main files and their responsibilities

- **`app.py`** — Flask application factory (`create_app`). Creates the shared
  `SQLAlchemy` instance `db`, configures the SQLite URI, registers the four
  blueprints under `/songs`, `/playlists`, `/users`, `/feed`, and calls
  `db.create_all()`. Tests inject an in-memory SQLite URI via the `config` arg.

- **`models.py`** — 6 SQLAlchemy models plus 3 association tables:
  - `User` (has `listening_streak`, `last_listened_at`, and a self-referential
    many-to-many `friends` relationship via the `friendships` table),
  - `Song` (title/artist/album/genre, `shared_by` FK to the sharer),
  - `Tag`, `ListeningEvent` (user listened to a song at a time),
  - `Rating` (1–5 score, unique per user+song),
  - `Playlist`, `Notification` (typed message for a recipient user).
  - Association tables: `friendships` (symmetric, stored as two directed rows),
    `song_tags`, and **`playlist_entries`** — a join table that carries an
    explicit **`position`** column, so songs in a playlist have an ordered
    position, not just insertion order (this is the table Issue #5 lives in).

- **`routes/songs.py`** — `GET /songs/search?q=`, `GET /songs/<id>`,
  `POST /songs/<id>/rate`, `POST /songs/<id>/listen`. Delegates to
  `search_service`, `notification_service.rate_song`, and
  `streak_service.record_listening_event`.

- **`routes/playlists.py`** — create playlist, `GET /playlists/<id>`,
  `GET /playlists/<id>/songs`, `POST /playlists/<id>/songs`. Delegates to
  `playlist_service` and `notification_service.add_to_playlist`.

- **`routes/users.py`** — user profile, `GET /users/<id>/streak`,
  notifications list, mark-notification-read.

- **`routes/feed.py`** — `GET /feed/<id>/listening-now` and
  `GET /feed/<id>/activity`, both delegating to `feed_service`.

- **`services/streak_service.py`** — `record_listening_event` (creates a
  `ListeningEvent` and calls `update_listening_streak`), and the pure function
  `update_listening_streak(user, now)` that mutates the streak counter.
  **(Issue #1)**

- **`services/feed_service.py`** — `get_friends_listening_now` (friends' events
  newer than `RECENT_THRESHOLD`, deduped to one most-recent event per friend) and
  `get_activity_feed` (most recent N events, no recency filter). **(Issue #2)**

- **`services/search_service.py`** — `search_songs` (title/artist ILIKE match)
  and `get_song`. **(Issue #3 — investigated, does not reproduce)**

- **`services/notification_service.py`** — `create_notification`,
  `add_to_playlist` (adds a song and notifies the sharer), `rate_song` (saves a
  rating — **but does not notify anyone**, Issue #4), `get_notifications`,
  `mark_as_read`.

- **`services/playlist_service.py`** — `create_playlist`, `get_playlist_songs`
  (ordered by `position`), `get_playlist`, `get_user_playlists`. **(Issue #5)**

- **`seed_data.py`** — drops/recreates the DB and inserts 5 users with
  friendships, 13 songs (0/1/3-tag variants), 3 playlists, recent + older
  listening events, and one playlist-add notification. The seed data is
  deliberately shaped to expose the bugs (e.g. recent events <30 min old vs.
  older events hours/days old for the listening-now window).

### Data flow trace #1 — how rating a song *should* trigger a notification

`POST /songs/<song_id>/rate` (`routes/songs.py:29`) parses `user_id` + `score`
→ calls `notification_service.rate_song(user_id, song_id, score)` → that function
validates the score, upserts a `Rating` row (respecting the unique
`user_id+song_id` constraint), and commits. **The notification for the song's
original sharer is never created** — compare `add_to_playlist` in the same file,
which *does* call `create_notification(user_id=song.shared_by, ...)`. There is no
separate rating-notification model; a notification is just a `Notification` row
with `notification_type="song_rated"`. This asymmetry is Issue #4.

### Data flow trace #2 — how a listening event updates a streak

`POST /songs/<song_id>/listen` (`routes/songs.py:43`) →
`streak_service.record_listening_event(user_id, song_id)` creates a
`ListeningEvent(listened_at=now)` and calls `update_listening_streak(user, now)`.
That pure function compares `now.date()` to `user.last_listened_at.date()`:
0 days → no change, 1 day → increment, >1 day → reset to 1. The streak counter and
`last_listened_at` live directly on the `User` row; there is no separate streak
table. The day-boundary comparison in this function is Issue #1.

### Patterns I noticed

1. **Thin routes, fat services.** Every route delegates immediately; business
   logic and all DB access are in `services/`. To debug any endpoint you trace
   route → the one service function it calls.
2. **Service functions own their own commits.** Each mutating service function
   calls `db.session.commit()` itself rather than the route doing it.
3. **State lives on the parent row, not in a side table** where it's a scalar:
   streak on `User`, no rating-count on `Song`. Ordered/relational state uses
   association tables (`playlist_entries.position`).
4. **Seed data is adversarial by design** — it plants exactly the edge-case rows
   (multi-tag songs, hours-old vs. minutes-old events, a 7-song playlist) needed
   to trigger each reported bug.

---

## Root Cause Analysis

### Issue #1 — My listening streak keeps resetting

**How I reproduced it.** Ran `pytest tests/test_streaks.py`. The test
`test_streak_increments_on_sunday` failed with `assert 1 == 2`: it records a
listen on Saturday 2024-06-15 (streak → 1), then Sunday 2024-06-16, and expects
the streak to increment to 2, but it reset to 1. I confirmed by hand that the
trigger is specifically **the second listen landing on a Sunday**, one calendar
day after the previous listen — no other weekday reproduces it.

**How I found the root cause.** Trace: `POST /songs/<id>/listen`
(`routes/songs.py:43`) → `record_listening_event` → `update_listening_streak`
(`streak_service.py:42`). Reading that function, every branch looked right
*except* the increment guard on line 73:
`elif days_since_last == 1 and today.weekday() != 6:`. The moment I was sure was
seeing `!= 6` — I confirmed in a REPL that Python's `datetime.weekday()` returns
**6 for Sunday** (Mon=0 … Sun=6). So the extra condition specifically excludes
Sundays from the "consecutive day" increment path.

**The root cause.** `datetime.weekday()` returns 6 for Sunday. The increment
branch required `days_since_last == 1 AND today.weekday() != 6`, so when the
current listen fell on a Sunday, the "listened yesterday" case failed its guard
and control fell through to the `else` branch, which resets the streak to 1. The
weekday check has no legitimate purpose — a streak is about *consecutive calendar
days* and does not care which day of the week it is — so any user who listened
Saturday then Sunday (a normal continuation) had their streak silently wiped
every Sunday.

**My fix and side-effect check.** I removed the `and today.weekday() != 6`
clause, leaving `elif days_since_last == 1:` to increment on any consecutive day
(`streak_service.py:73`). I checked both sides of the day boundary: all 5 streak
tests pass — Sunday now increments (`test_streak_increments_on_sunday`), a
genuinely skipped day still resets (`test_streak_resets_after_skipped_day`,
Mon→Wed → 1), same-day double listens still don't double count, and new users
still start at 1. No other code reads `weekday()`, so nothing else is affected.

---

*(Remaining entries below.)*
