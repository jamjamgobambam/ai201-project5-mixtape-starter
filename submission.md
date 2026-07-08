
# Mixtape Bug Hunt — Submission

## Codebase Map

### Top-level files

- **app.py** — Flask application factory (`create_app`). Initializes `SQLAlchemy` (`db`), registers four blueprints (`songs`, `playlists`, `users`, `feed`) under their respective URL prefixes, and calls `db.create_all()` on startup.
- **models.py** — Defines all SQLAlchemy models: `User`, `Tag`, `Song`, `ListeningEvent`, `Rating`, `Playlist`, `Notification`. Also defines three association tables: `friendships` (symmetric many-to-many between users), `song_tags` (many-to-many between songs and tags), and `playlist_entries` (many-to-many between playlists and songs, but with an explicit `position` column — songs in a playlist have an ordering, not just insertion order).
- **seed_data.py** — Populates the database with 5 users and their friendships, 10 tags, 13 songs (deliberately split into songs with 0, 1, and 3+ tags), a mix of recent and older listening events, 3 playlists, and one working notification. The varying tag counts on songs are clearly there to expose the search duplication bug.

### routes/ — thin controllers

Every route file follows the same pattern: parse the request, call a service function, format the response as JSON. No business logic lives in routes.

- **songs.py** → calls `search_service.search_songs` / `get_song`, `notification_service.rate_song`, `streak_service.record_listening_event`
- **playlists.py** → calls `playlist_service.create_playlist` / `get_playlist_songs` / `get_playlist`, `notification_service.add_to_playlist`
- **users.py** → calls `streak_service.get_streak`, `notification_service.get_notifications` / `mark_as_read`
- **feed.py** → calls `feed_service.get_friends_listening_now` / `get_activity_feed`

### services/ — where the business logic (and the bugs) live

- **streak_service.py** — `record_listening_event` creates a `ListeningEvent` row and calls `update_listening_streak`, which compares `user.last_listened_at.date()` to `today` to decide whether to increment, hold, or reset the streak.
- **feed_service.py** — `get_friends_listening_now` filters listening events to a 24-hour `RECENT_THRESHOLD` window, then deduplicates so only the most recent song per friend is shown.
- **search_service.py** — `search_songs` does an `outerjoin` against `song_tags` and filters by title/artist match, then calls `.to_dict()` on each row returned by the query.
- **notification_service.py** — `add_to_playlist` creates a `Notification` after adding a song to a playlist. `rate_song` saves a `Rating` but has no corresponding call to `create_notification` anywhere in the function.
- **playlist_service.py** — `get_playlist_songs` queries songs ordered by `position`, then returns `songs[:-1]` before mapping to dicts.

### Pattern I noticed

Every route delegates immediately to a service function — routes only parse input and shape the response; all logic and DB writes happen in `services/`. The `to_dict()` method on each model is the single serialization point, so any bug visible in JSON output usually traces back to either the query logic in a service function or a relationship defined in `models.py`.

### Data flow trace: user rates a song

1. Client sends `POST /songs/<song_id>/rate` with `user_id` and `score` in the JSON body.
2. `routes/songs.py::rate()` parses the body, validates that `user_id` and `score` are present, then calls `notification_service.rate_song(user_id, song_id, score)`.
3. `rate_song()` validates the score is between 1 and 5, confirms the song and user exist, checks whether a `Rating` already exists for that user/song pair (there's a unique constraint on `user_id` + `song_id`), then either updates the existing `Rating` or creates a new one, and commits.
4. The route serializes the returned `Rating` object back to the client as JSON.

Notably, `rate_song()` never calls `create_notification()`, unlike the parallel `add_to_playlist()` function in the same file, which explicitly notifies the song's original sharer after modifying the playlist. This asymmetry is the shape of Issue #4 — the rating is saved correctly, but no notification is ever generated for it.

---

## AI Usage

*(To be filled in throughout the project — will describe what I asked AI to explain, trace, or summarize, and where I had to verify or correct its explanation.)*

---

## Root Cause Analysis Entries

*(To be filled in as each bug is investigated and fixed — Milestone 3.)*