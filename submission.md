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
| 1 | Listening streak keeps resetting | `streak_service.py` | Likely fix |
| 2 | Friends Listening Now shows people from yesterday | `feed_service.py` | Candidate |
| 3 | Same song shows twice in search | `search_service.py` | Likely fix |
| 4 | Notified on playlist-add but not on rating | `notification_service.py` | Likely fix |
| 5 | Last song in a playlist never shows up | `playlist_service.py` | Candidate |

I'll confirm which 3+ to fix in the next milestone by reproducing each first.
