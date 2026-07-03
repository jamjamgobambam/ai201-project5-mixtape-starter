# Mixtape Bug Hunt — Submission

**Author:** Pratik Patil
**Branch:** `bugfix/mixtape`
**Scope completed:** All 5 bugs fixed + regression tests (both stretch goals).

---

## AI Usage

<!-- Filled in during Milestone 4 — see the "AI Usage (detailed)" section at the bottom. -->
I used an AI assistant (Claude) primarily as a **navigation and tracing partner** for an
unfamiliar codebase, and to **verify hypotheses by running code**, not to guess at bugs.
See the full [AI Usage (detailed)](#ai-usage-detailed) section at the end for a bug-by-bug
account of what the AI helped with and where I had to confirm things myself.

---

## Codebase Map

Mixtape is a Flask + SQLAlchemy social-music API. There is no HTML frontend — every feature is
a JSON endpoint. The architecture is a clean three-layer split:

**`app.py`** — the application factory (`create_app`). Creates the Flask app, configures the
SQLite database (`sqlite:///mixtape.db`), initializes the shared `db = SQLAlchemy()` object,
registers the four route blueprints under URL prefixes (`/songs`, `/playlists`, `/users`,
`/feed`), and calls `db.create_all()`. **Important:** the app must be started with
`FLASK_APP=app:create_app flask run` — running `python app.py` triggers a SQLAlchemy
double-import error because `models.py` imports `db` from `app`.

**`models.py`** — defines 6 SQLAlchemy models plus 3 association tables:
- `User` — has `listening_streak` and `last_listened_at` columns (used by streaks), and a
  self-referential many-to-many `friends` relationship via the `friendships` table.
- `Song` — shared by a user (`shared_by` FK); has a `tags` many-to-many (via `song_tags`).
- `ListeningEvent` — one row per listen (`user_id`, `song_id`, `listened_at`). This is the
  source of truth for both streaks and the "listening now" feed.
- `Rating` — a user's 1–5 score for a song, with a `UniqueConstraint(user_id, song_id)` so a
  user has at most one rating per song.
- `Playlist` — has an ordered `songs` many-to-many via the **`playlist_entries`** association
  table, which carries an explicit `position` integer column — songs have a defined order, not
  just insertion order.
- `Notification` — a message for a `user_id` with a `notification_type` and `body`.

**`routes/`** — thin HTTP layer. Each route parses request input, calls exactly one service
function, and formats the JSON response (including 400/404 error mapping). No business logic
lives here.
- `routes/songs.py` — `/songs/search`, `/songs/<id>`, `/songs/<id>/rate`, `/songs/<id>/listen`
- `routes/playlists.py` — create playlist, get playlist, `/playlists/<id>/songs` (get + add)
- `routes/users.py` — user profile, `/users/<id>/streak`, `/users/<id>/notifications`
- `routes/feed.py` — `/feed/<id>/listening-now`, `/feed/<id>/activity`

**`services/`** — all business logic. This is where the five bugs live:
- `streak_service.py` — increments/resets `listening_streak` based on consecutive calendar days.
- `feed_service.py` — "Friends Listening Now" (recency-filtered) and the general activity feed.
- `search_service.py` — song search by title/artist.
- `notification_service.py` — creates notifications; also owns `add_to_playlist` and `rate_song`.
- `playlist_service.py` — playlist creation and ordered song retrieval.

**`seed_data.py`** — wipes and repopulates the DB with 5 users (with friendships), 13 songs
(deliberately split into 0-tag, 1-tag, and 3-tag groups to exercise the search bug), 3
playlists, listening events (some within the past ~30 min, some 2h–14 days old), streaks, and a
sample "song added to playlist" notification (so the working notification pattern is visible
when investigating Issue #4).

### Data flow — user rates a song (traced end to end)

1. `POST /songs/<song_id>/rate` with JSON `{user_id, score}` → `routes/songs.py::rate()`.
   The route validates that `user_id` and `score` are present, then calls the service.
2. `notification_service.rate_song(user_id, song_id, score)` validates the score is 1–5, loads
   the `Song` and rater `User`, then **upserts** a `Rating`: if a row already exists for
   `(user_id, song_id)` it updates the score, otherwise it inserts a new `Rating`. It commits
   and returns the `Rating`.
3. The route serializes `rating.to_dict()` and returns `201`.

Compare this to `add_to_playlist()` in the same file, which — after mutating data — also calls
`create_notification(...)` to notify the song's original sharer. `rate_song()` does **not** do
that final step, which is exactly Issue #4.

### Patterns I noticed

- **Routes delegate immediately to one service function.** Input parsing and response
  formatting live in `routes/`; all logic lives in `services/`. To fix an endpoint bug, trace
  back to the single service it calls (the README says this explicitly).
- **`ListeningEvent` is the shared substrate** for two very different features (streaks and the
  feed), so date/time handling shows up in both — and two of the five bugs are date/time
  boundary errors.
- **Association tables carry data**, not just FKs: `playlist_entries.position` and
  `playlist_entries.added_by` matter for ordering and attribution.
- **The service layer relies on some implicit SQLAlchemy behavior** (e.g. legacy
  `Query.all()` entity de-duplication), which is where Issue #3 hides.

---

## Root Cause Analyses

<!-- One entry per bug, added as each fix is committed. -->

### Issue #1 — My listening streak keeps resetting

**How I reproduced it.** Two ways. (1) The repo already ships a test,
`tests/test_streaks.py::test_streak_increments_on_sunday`, that listens on Saturday then Sunday
and asserts the streak becomes 2 — it failed with `assert 1 == 2`. (2) I called
`update_listening_streak(user, saturday)` then `update_listening_streak(user, sunday)` directly
in a script (Saturday = `datetime(2024,6,15)`, Sunday = `2024,6,16`): the streak stayed at 1
instead of incrementing to 2. Any consecutive listen where "today" is a Sunday failed to count.

**How I found the root cause.** The route `POST /songs/<id>/listen` → `record_listening_event`
→ `update_listening_streak` in `services/streak_service.py`. Reading that function, the streak
math is a three-way branch on `days_since_last`. The `days_since_last == 1` branch (the
"listened yesterday, so increment" case) had an extra condition: `and today.weekday() != 6`.
The moment I confirmed it: `datetime.weekday()` returns **6 for Sunday**, so on Sundays that
`and` clause is `False`, the elif is skipped, and control falls through to the `else`, which
**resets the streak to 1**.

**The root cause.** `datetime.weekday()` uses Monday=0 … Sunday=6. The condition
`days_since_last == 1 and today.weekday() != 6` means "increment only if yesterday was
consecutive **and today is not Sunday**." There is no valid reason to exclude Sundays — a
Saturday→Sunday listen is just as consecutive as any other pair of days. The stray
`today.weekday() != 6` clause caused every Sunday listen to be misclassified as a broken streak
and reset to 1, so users who listened daily lost their streak every Sunday.

**My fix and side-effect check.** I removed the `and today.weekday() != 6` clause so the branch
is simply `elif days_since_last == 1:` — a consecutive-day listen increments the streak on any
day of the week. Side effects checked: the other three branches are untouched, so
`days_since_last == 0` (same day → no change), `== 1` (increment), and `>= 2` (skipped a day →
reset to 1) all still hold. I re-ran the full `test_streaks.py` suite: all 5 tests pass
(previously 4/5), including `test_streak_does_not_double_count_same_day` and
`test_streak_resets_after_skipped_day`, confirming the reset-on-real-gap behavior still works.

### Issue #2 — Friends Listening Now shows people from yesterday

**How I reproduced it.** I seeded the DB and called `get_friends_listening_now(user_id)` for
every user, printing how long ago each returned friend actually listened. Three users
(`darius`, `simone`, `kenji`) had **nova** returned as "listening now" even though nova's most
recent listen was **122 minutes ago**. The seed data comments confirm the intent: events
"within the past 30 minutes … should appear in 'listening now'", while events "1–14 days ago …
should NOT appear." So a 2-hour-old listen showing up is the reported bug.

**How I found the root cause.** `GET /feed/<id>/listening-now` → `get_friends_listening_now` in
`services/feed_service.py`. The function is correct in shape — it computes
`cutoff = now - RECENT_THRESHOLD`, filters `ListeningEvent.listened_at >= cutoff`, and
de-duplicates to one (most recent) event per friend. The de-dup is why the bug is intermittent:
if a friend *also* has a truly-recent event, only that recent one is shown and the staleness is
hidden. It only surfaces for a friend whose single most-recent event is stale-but-within-window
(nova, for kenji/darius/simone). That pointed me one line up, to the module constant.

**The root cause.** `RECENT_THRESHOLD = timedelta(hours=24)`. "Friends Listening Now" is meant
to show who is *currently* listening, but a 24-hour window admits anyone who listened at any
point in the last day — i.e. "people from yesterday." The filter and de-dup logic were both
correct; the window constant was simply an order-of-magnitude too large for the feature's
meaning.

**My fix and side-effect check.** I changed `RECENT_THRESHOLD` to `timedelta(minutes=30)`,
matching the "past 30 minutes" definition documented in the seed data. Boundary check on both
sides: after the fix, the three sub-30-minute seed events (10/15/20 min ago) still appear —
nova's feed correctly shows all three friends — while nova's 122-minute-old event and all the
2h–14-day events are correctly excluded (kenji's feed, whose only in-window candidate was that
stale nova event, is now empty). I also confirmed the change does not touch `get_activity_feed`,
which is intentionally *not* recency-filtered (its docstring says so) and still returns the most
recent N events regardless of age.
