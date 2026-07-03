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
