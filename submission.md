# Mixtape — Bug Hunt Submission

## Milestone 1 — Codebase Map

### Main files and their roles

**`app.py`** — Flask application factory (`create_app`). Initializes the single `SQLAlchemy` instance (`db`), wires config (SQLite at `mixtape.db` by default), registers the four route blueprints under their URL prefixes (`/songs`, `/playlists`, `/users`, `/feed`), and calls `db.create_all()`.

**`models.py`** — All SQLAlchemy models and association tables:
- **User** — has `listening_streak`, `last_listened_at`, and a self-referential many-to-many `friends` relationship via the `friendships` table.
- **Song** — shared by a user (`shared_by` FK); has ratings, listening events, and tags.
- **Tag** — song genre/mood labels, joined to songs via the `song_tags` table.
- **ListeningEvent** — one row per "user listened to song at time T"; drives streaks and the feed.
- **Rating** — a user's 1–5 score for a song, with a `UniqueConstraint(user_id, song_id)` so one rating per user per song.
- **Notification** — a message for a recipient user, with `notification_type`, `body`, and `read` flag.
- **Playlist** — songs are attached through the **`playlist_entries`** association table, which carries extra columns: `position` (explicit ordering), `added_by`, and `added_at`. So playlist order is stored explicitly, not by insertion order.

**`routes/`** — Thin HTTP layer. Each blueprint parses the request, calls a service function, and formats the JSON response. No business logic lives here.
- `songs.py` — search, song detail, rate, listen.
- `playlists.py` — create playlist, get playlist, list songs, add song.
- `users.py` — user detail, streak, notifications, mark notification read.
- `feed.py` — "friends listening now" and activity feed.

**`services/`** — All business logic. The five bugs live here.
- `streak_service.py` — records listening events and updates the consecutive-day streak.
- `feed_service.py` — "friends listening now" (recency-filtered) and activity feed (last N).
- `search_service.py` — song search by title/artist.
- `notification_service.py` — creating notifications, adding songs to playlists, rating songs.
- `playlist_service.py` — playlist creation and retrieval of ordered songs.

**`seed_data.py`** — Populates the DB with 5 users, 13 songs, 3 playlists, 10 tags for testing.

### Data flow — sharing/rating a song triggers a notification

When a friend adds your shared song to a playlist:

`POST /playlists/<playlist_id>/songs` → `routes/playlists.py::add_song()` parses `song_id` + `added_by` → calls `notification_service.add_to_playlist(playlist_id, song_id, added_by)`. That service appends the song to `playlist.songs` (writing a `playlist_entries` row) and, **if the adder isn't the original sharer**, calls `create_notification(user_id=song.shared_by, type="song_added_to_playlist", ...)`, which inserts a `Notification` row for the sharer. The sharer later reads it via `GET /users/<user_id>/notifications` → `get_notifications()`.

The parallel rating flow: `POST /songs/<song_id>/rate` → `routes/songs.py::rate()` → `notification_service.rate_song()`. This saves/updates the `Rating` — but, unlike `add_to_playlist`, it does **not** call `create_notification`. (This is the architectural shape behind Issue #4.)

### Patterns I noticed

- **Routes delegate immediately to services.** Routes only do input validation and response shaping; all logic is in `services/`. Errors are surfaced by raising `ValueError` in the service and translating it to a 4xx in the route.
- **Single shared `db` instance** defined in `app.py` and imported everywhere — must be imported as `from app import db`, never by re-instantiating (this is why `python app.py` double-imports and breaks; use `flask run`).
- **Datetimes are timezone-aware UTC** (`datetime.now(timezone.utc)`), though some stored values may be naive and get normalized on read.
- **Association tables carry data** (`playlist_entries.position`, `friendships`) — ordering and relationships are explicit, not implicit.

---

## The Five Open Issues (read; rough plan)

| # | Title | Service | Plan |
|---|-------|---------|------|
| 1 | Listening streak keeps resetting | `streak_service.py` | **Chosen** |
| 2 | Friends Listening Now shows people from yesterday | `feed_service.py` | Candidate (stretch) |
| 3 | Same song shows twice in search | `search_service.py` | Attempted — did not reproduce (see below) |
| 4 | Notified on playlist-add but not on rating | `notification_service.py` | **Chosen** |
| 5 | Last song in a playlist never shows up | `playlist_service.py` | **Chosen** |

**Chosen three: #1, #4, #5.**

---

## Milestone 2 — Reproduction (before any fix)

> All reproductions run service functions directly against the seeded DB; no code was changed. Streak repro uses uncommitted in-memory users (rolled back); the rating repro deletes the row it creates to restore DB state.

### Bug #1 — Listening streak keeps resetting

**How I reproduced it:** Created an in-memory user with `listening_streak=5` who "listened yesterday," then called `update_listening_streak(user, now)` three times with `now` set to a Saturday, a Sunday, and a Monday.

| `now` day | weekday() | streak 5 → |
|-----------|-----------|------------|
| Saturday | 5 | **6** (increments, correct) |
| Sunday | 6 | **1** (resets — BUG) |
| Monday | 0 | **6** (increments, correct) |

A consecutive-day listen that lands on a **Sunday** resets the streak instead of incrementing it. Any user listening every day loses their streak every Sunday.

### Bug #4 — Notified on playlist-add but not on rating

**How I reproduced it:** Had `nova` rate `simone`'s song "Crown Heights Anthem" 5 stars via `rate_song()`, then checked `get_notifications(simone.id)`. Simone's notification count stayed `0 → 0`, and there were zero `song_rated` notifications. By contrast, `add_to_playlist()` does generate a `song_added_to_playlist` notification for the sharer. So rating produces no notification at all.

### Bug #5 — Last song in a playlist never shows up

**How I reproduced it:** For each seeded playlist, compared the true entry count in `playlist_entries` against what `get_playlist_songs()` returns.

| Playlist | Entries in DB | Returned by service | Missing |
|----------|---------------|---------------------|---------|
| Late Night Vibes | 7 | 6 | 1 |
| Friday Energy | 7 | 6 | 1 |
| Study Mode | 7 | 6 | 1 |

Every playlist returns exactly one fewer song than it contains — the highest-`position` (last) song is always dropped.

### Bug #3 — Attempted, did not reproduce (why)

Searching for the 3-tag song "Crown Heights Anthem" returned `count=1`, not a duplicate. `search_songs()` uses `db.session.query(Song)` (the legacy Query API), which automatically de-duplicates ORM entities by primary key, so the `outerjoin` on `song_tags` does not actually surface duplicate `Song` rows. The real trigger appears to be a separate, conditional code path; I set this aside in favor of three bugs I could reproduce deterministically. May revisit as a stretch goal.

---

## Milestone 3 — Root Cause Analysis

### Bug #1 — My listening streak keeps resetting

**How I reproduced it:** Created an in-memory user with `listening_streak=5` who listened "yesterday," then called `update_listening_streak(user, now)` with `now` on a Saturday, Sunday, and Monday. Saturday and Monday incremented the streak to 6; Sunday reset it to 1. The existing test `test_streak_increments_on_sunday` also failed (`assert 1 == 2`), confirming it independently.

**How I found the root cause:** Started at the route `GET /users/<id>/streak` (`routes/users.py`) → `streak_service.get_streak`, but the streak is *written* by `record_listening_event` → `update_listening_streak`. Reading that function, line 73 stood out: `elif days_since_last == 1 and today.weekday() != 6:`. The extra `today.weekday() != 6` clause has nothing to do with the documented streak rules in the function's own docstring, which made me confident this was the cause rather than just a suspicious area.

**The root cause:** Python's `datetime.weekday()` returns `6` for Sunday. The consecutive-day branch was guarded by `days_since_last == 1 and today.weekday() != 6`. On any Sunday, `today.weekday() != 6` is `False`, so the `elif` failed and execution fell through to the `else` branch, which resets the streak to 1 — even though the user listened on a perfectly consecutive day. So every Sunday silently broke an ongoing streak.

**My fix and side-effect check:** Removed the `and today.weekday() != 6` clause (line 73), leaving `elif days_since_last == 1:`. The weekday has no bearing on whether two dates are consecutive, so this restores the documented rule. I re-ran all 5 streak tests (new-user start, consecutive increment, same-day no-double-count, skipped-day reset, and the Sunday case) — all pass. The same-day (`days_since_last == 0`) and skipped-day (`> 1`) branches are untouched, so both sides of the boundary still behave correctly.

*AI use:* Used the assistant to scan `weekday()` semantics and confirm `6 == Sunday`, and to trace the route→service write path.

### Bug #5 — The last song in a playlist never shows up

**How I reproduced it:** For each seeded playlist, compared the true row count in the `playlist_entries` table against the length returned by `get_playlist_songs()`. Every 7-entry playlist returned exactly 6 songs, always missing the highest-`position` (last) one. The existing tests `test_playlist_returns_all_songs` (`assert len == 5`) and `test_playlist_returns_songs_in_order` also failed.

**How I found the root cause:** Traced `GET /playlists/<id>/songs` (`routes/playlists.py::get_songs`) → `playlist_service.get_playlist_songs`. The query itself was correct — it joins `playlist_entries`, filters by playlist, and orders ascending by `position`. The bug was on the very last line, in the return expression rather than the query: `return [song.to_dict() for song in songs[:-1]]`. The `[:-1]` slice is what made it conclusive — the docstring explicitly says "returns all songs," yet the slice silently drops one.

**The root cause:** The list comprehension iterated over `songs[:-1]` instead of `songs`. Python's `[:-1]` slice returns every element *except the last*, so the song with the highest position was always discarded after a correctly-ordered query. Because results are ordered ascending by `position`, the dropped element was always the last song in the playlist.

**My fix and side-effect check:** Changed `songs[:-1]` to `songs` so all rows are returned. Verified both boundaries: a populated playlist now returns all songs in correct position order, and an empty playlist still returns `[]` without error (`[][:-1]` and `[]` are both empty, so the edge case never regressed). All 3 playlist tests pass.

*AI use:* Minimal — the assistant confirmed Python slice semantics (`[:-1]` excludes the last element).
