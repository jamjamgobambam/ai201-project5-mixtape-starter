# Project 5 — Mixtape Bug Hunt · Submission

## AI Usage

I used an AI assistant (Claude, via Claude Code) throughout this project. Its role and my
verification are described honestly below.

**Where AI helped — codebase navigation & orientation.** I asked the assistant to summarize each
service module's responsibility and to trace two call chains end to end (rating a song; viewing a
playlist). This accelerated building the codebase map: instead of reading all four route files and
five service files cold, I had the assistant produce a first-pass map of "route → service → model"
for every endpoint, then I read the code to confirm each claim.

**Where AI helped — bug triage.** For each reported issue I asked the assistant to point at the
suspicious function and explain what it does. This was fastest for the mechanical bugs
(`weekday() != 6`, the `[:-1]` slice) where the defect is visible once you're looking at the right
line.

**Where I verified / overrode the AI.** I did **not** take any diagnosis on faith. Every root cause
was confirmed by running code:
- I ran the existing test suite to establish a baseline (3 failing, 10 passing) before touching
  anything — this immediately confirmed #1 (streak) and #5 (playlist) and, crucially, showed the
  search duplicate tests **passing**.
- For **Issue #3 (search duplicates)** the AI initially described it as a live duplicate bug. I
  disproved that by probing the database directly: the raw SQL join returns 3 rows for a 3-tag song,
  but `db.session.query(Song).all()` returns 1 because SQLAlchemy's ORM deduplicates entities by
  primary key. So the reported symptom does not reproduce as written — it is a *latent* defect. I
  documented and fixed it on that basis rather than claiming a reproduction I never got. This is the
  clearest example of where reading and running the code myself corrected the AI's first answer.
- For **Issue #2 (feed window)** the AI could identify the 24-hour constant but not the "correct"
  value — that was a product-semantics judgment I made by reading the seed data's own definition of
  recent activity ("the past 30 minutes").

In short: AI was a fast navigator and explainer for code I then verified myself; it was unreliable
as a diagnostician until I confirmed each claim by executing the code.

---

## Codebase Map

**Architecture.** Mixtape is a Flask + SQLAlchemy app with a strict two-layer separation:

```
HTTP request → routes/*.py   (parse input, format JSON, map ValueError → HTTP status)
             → services/*.py  (ALL business logic and orchestration)
             → models.py      (SQLAlchemy ORM) → SQLite (instance/mixtape.db)
```

Every route delegates immediately to a service function and contains no business logic of its own.
This is the dominant pattern in the code, and it is why all five bugs live in `services/` — the
routes are thin pass-throughs.

**Main files and their roles:**

- **`app.py`** — application factory (`create_app`) and the shared `db = SQLAlchemy()` instance.
  Registers four blueprints under `/songs`, `/playlists`, `/users`, `/feed`.
- **`models.py`** — five entity models plus association tables:
  - `User` — carries streak state directly on the row (`listening_streak`, `last_listened_at`).
  - `Song` — `shared_by` FK points at the original sharer (the person notified about the song).
  - `Tag` + `song_tags` (association table) — songs have a many-to-many set of tags (0, 1, or 3+).
  - `Rating` — score 1–5, with a `UniqueConstraint(user_id, song_id)`: one rating per user per song.
  - `ListeningEvent` — one row per listen; the source of truth for both streaks and the feed.
  - `Playlist` + `playlist_entries` (association table) — **a join table with an explicit
    `position` column**, so song order is stored, not inferred from insertion. It also records
    `added_by` and `added_at`.
  - `Notification` — `user_id` is the recipient; has a `notification_type`, `body`, and `read` flag.
- **`routes/`** — `songs.py` (search / detail / rate / listen), `playlists.py` (create / detail /
  list songs / add song), `users.py` (profile / streak / notifications), `feed.py` (listening-now /
  activity).
- **`services/`** — `streak_service.py`, `feed_service.py`, `search_service.py`,
  `notification_service.py`, `playlist_service.py`. This is where the bugs are.
- **`seed_data.py`** — rebuilds the DB with 5 users, 25 songs (deliberately spanning 0/1/3+ tags),
  3 playlists, and listening events at carefully chosen ages (some minutes old, some hours/days old)
  that encode the *intended* behaviour of the feed and search features.

**Data flow — rating a song (traced end to end):**
`POST /songs/<song_id>/rate` → `routes/songs.py:rate()` parses `user_id` and `score` →
`notification_service.rate_song(user_id, song_id, score)` validates the score, looks up the song and
rater, then **upserts** a `Rating` (updates the existing row if the user already rated the song,
thanks to the unique constraint; otherwise inserts). The route serializes the returned `Rating` to
JSON. (Issue #4 lives here: this flow should also notify the song's sharer, and originally did not.)

**Data flow — viewing a playlist:**
`GET /playlists/<id>/songs` → `routes/playlists.py:get_songs()` →
`playlist_service.get_playlist_songs()` joins `Song` to `playlist_entries`, filters by playlist, and
orders by `playlist_entries.position` (explicit stored order). (Issue #5 lived here.)

**Pattern worth noting:** notifications are created by a single helper, `create_notification`, which
both `add_to_playlist` and (after my fix) `rate_song` call. Comparing which service functions do and
don't call it is exactly how Issue #4 was found.

---

## Root Cause Analysis

<!-- RCA entries are appended here as each bug is fixed. -->

### Issue #1: My listening streak keeps resetting

- **How you reproduced it:** I ran the existing test suite first (`pytest tests/`) to establish a
  baseline. `tests/test_streaks.py::test_streak_increments_on_sunday` failed with `assert 1 == 2`:
  it listens on Saturday (streak → 1) then Sunday and expects the streak to become 2, but the code
  left it at 1. That test isolates the exact condition — a streak that continues into a Sunday.
- **How you found the root cause:** I followed the streak feature from the route down:
  `POST /songs/<id>/listen` → `routes/songs.py:listen()` → `streak_service.record_listening_event()`
  → `update_listening_streak(user, now)`. Reading `update_listening_streak`, the increment branch was
  `elif days_since_last == 1 and today.weekday() != 6:`. The moment I saw `weekday() != 6` I checked
  what `datetime.weekday()` returns — Monday is 0 and **Sunday is 6** — and it was clear the branch
  deliberately excluded Sundays.
- **The root cause:** `datetime.weekday()` returns `6` for Sunday. The increment branch only ran when
  `days_since_last == 1` **and** `today.weekday() != 6`, so any consecutive-day listen that fell on a
  Sunday skipped the `+= 1` branch and dropped into the `else`, which resets the streak to `1`. There
  is no legitimate reason for a streak to reset on Sundays; the weekday clause was simply wrong.
- **Your fix and side-effect check:** I removed the `and today.weekday() != 6` clause so the branch is
  just `elif days_since_last == 1:` and added a comment explaining why (consecutive days always
  increment). Side-effect check: I re-ran all of `tests/test_streaks.py` — the new-user (streak = 1),
  same-day (no double count), and skipped-day (reset to 1) cases all still pass, so the fix corrects
  the Sunday case without weakening the reset/increment logic on other days. 5 passed.
