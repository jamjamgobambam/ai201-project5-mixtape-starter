# Project 5 — Mixtape Bug Hunt: Submission

## AI Usage

I used Claude Code (Opus) as a navigation and verification aid, not a bug-guesser:

- **Orientation:** I asked it to summarize each `services/` file's responsibility and the route → service call chains so I could build the codebase map without reading every line top-to-bottom.
- **Reproduction:** For Issue #2 (feed) I had it cross-reference `feed_service.py` against the comments in `seed_data.py` (`"should NOT appear in 'listening now' after fix"`), which is what pinned the threshold as the root cause rather than a timezone issue I first suspected.
- **Verification I did myself:** I confirmed each root cause by reading the exact line and reasoning about the values (e.g. `datetime.weekday()` returns 6 for Sunday; `songs[:-1]` drops the last element; the `outerjoin` on a multi-tag song fans out rows). The AI's first instinct on Issue #2 was "timezone mismatch," which I overrode after reading the seed data and seeing the threshold was simply too wide.

---

## Codebase Map

**`app.py`** — Flask app factory (`create_app`) and the shared SQLAlchemy `db` instance.

**`models.py`** — Six entities. `User`, `Song`, `Playlist`, `ListeningEvent`, `Rating`, `Notification`, plus three association tables: `friendships` (symmetric self-join on User), `song_tags` (Song↔Tag), and `playlist_entries` (Playlist↔Song with an explicit `position` column — playlist order is stored, not implied by insertion).

**`routes/`** — Thin HTTP layer. Each route parses input, calls one service function, and JSON-formats the result. `songs.py`, `playlists.py`, `users.py`, `feed.py`.

**`services/`** — All business logic:
- `streak_service.py` — records listening events and updates consecutive-day streaks.
- `feed_service.py` — "Friends Listening Now" (recency-filtered) and general activity feed.
- `search_service.py` — song search by title/artist.
- `notification_service.py` — creates/reads notifications; also owns `add_to_playlist` and `rate_song`.
- `playlist_service.py` — playlist creation and ordered song retrieval.

**Pattern:** every route delegates immediately to a service; all logic lives in `services/`. Notifications are always addressed to `song.shared_by` (the original sharer).

### Data flow — a friend adds your song to a playlist (Issue #4's working analog)
`POST /playlists/<id>/songs` → `routes/playlists.py` → `notification_service.add_to_playlist(playlist_id, song_id, adder_id)`. That function appends the song to `playlist.songs`, then — **if the adder is not the sharer** — calls `create_notification(user_id=song.shared_by, type="song_added_to_playlist", ...)`, which inserts a `Notification` row for the sharer. `rate_song` follows the same route→service shape but originally skipped the final notification step (Issue #4).

---

## Root Cause Analyses

### Issue #1 — My listening streak keeps resetting
- **How reproduced:** Called `update_listening_streak(user, now)` with `last_listened_at` set to exactly one day earlier, where "today" falls on a Sunday. The streak reset to 1 instead of incrementing.
- **Finding the root cause:** Route `users.py` → `streak_service.update_listening_streak`. Read the branch handling `days_since_last == 1`.
- **Root cause:** The consecutive-day branch was `elif days_since_last == 1 and today.weekday() != 6:`. `datetime.weekday()` returns 6 for Sunday, so on Sundays the condition was false and control fell through to the `else`, resetting the streak to 1 — even though the user listened on consecutive days. There is no legitimate reason for Sunday to break a streak; the weekday check was spurious.
- **Fix & side-effect check:** Removed `and today.weekday() != 6`, leaving `elif days_since_last == 1:`. Verified the other branches (first-ever listen → 1, same-day → no change, gap > 1 day → reset to 1) still behave correctly on both Saturday and Sunday.

### Issue #2 — Friends Listening Now shows people from yesterday
- **How reproduced:** Seeded the DB and hit `GET /<nova_id>/listening-now`. Friends whose only recent event was hours old (up to ~18h ago) appeared, though `seed_data.py` labels those events "should NOT appear in 'listening now'."
- **Finding the root cause:** `feed.py` → `feed_service.get_friends_listening_now`. Compared the `RECENT_THRESHOLD` constant against the seed comments distinguishing "past 30 minutes" (recent) from "1–14 days ago" (older).
- **Root cause:** `RECENT_THRESHOLD = timedelta(hours=24)`. "Listening now" is meant to be near-real-time, but a 24-hour cutoff includes everything a friend played earlier today or last night. The seed data intentionally places "old" events 2–18 hours back to expose this.
- **Fix & side-effect check:** Changed the threshold to `timedelta(minutes=30)` so only genuinely-current listens surface. Confirmed `get_activity_feed` is unaffected (it deliberately ignores recency and uses `limit`).

### Issue #3 — The same song keeps showing up twice in search
- **How reproduced:** `GET /songs/search?q=` matching a song with 3 tags (e.g. "Crown Heights Anthem") returned that song 3 times; songs with 0 or 1 tag appeared once.
- **Finding the root cause:** `songs.py` → `search_service.search_songs`. The query does `.outerjoin(song_tags, ...)`.
- **Root cause:** Joining `song_tags` produces one row per (song, tag) pair, so a song with N tags yields N duplicate `Song` rows. The join isn't even needed — the filter only touches `title`/`artist`, and tags are loaded separately via the `Song.tags` relationship. This is the "conditional" duplicate: it only triggers for songs with ≥2 tags.
- **Fix & side-effect check:** Removed the unnecessary `.outerjoin(song_tags, ...)`. Search now returns each matching song once; tags still populate via `to_dict()`. Verified 0-tag and 1-tag songs still return correctly and matching is unchanged.

### Issue #4 — Notified on playlist-add but not on rating
- **How reproduced:** Called `rate_song(other_user, song, 5)` on a song shared by nova, then checked nova's notifications — none created, whereas `add_to_playlist` did create one.
- **Finding the root cause:** `songs.py` → `notification_service.rate_song`. Compared it line-by-line to the working `add_to_playlist` in the same file.
- **Root cause:** `rate_song` persisted the `Rating` but never called `create_notification`. `add_to_playlist` has the notify-the-sharer step; `rate_song` was simply missing it — an architectural omission, not a typo.
- **Fix & side-effect check:** After committing the rating, added a `create_notification` call to `song.shared_by` (type `song_rated`) guarded by `song.shared_by != user_id`, mirroring the playlist pattern. Verified self-ratings don't self-notify and existing rating create/update logic is unchanged.

### Issue #5 — The last song in a playlist never shows up
- **How reproduced:** Seeded playlists with 7 songs, called `get_playlist_songs(playlist_id)` — only 6 returned, always missing the highest-position song.
- **Finding the root cause:** `playlists.py` → `playlist_service.get_playlist_songs`. Read the return statement.
- **Root cause:** The return was `return [song.to_dict() for song in songs[:-1]]`. The `[:-1]` slice drops the last element of the position-ordered list, so the final song is always omitted.
- **Fix & side-effect check:** Changed `songs[:-1]` to `songs`. Verified ordering (still `ORDER BY position ASC`) and that empty playlists still return `[]`.

---

## Regression Test

See `tests/test_playlists.py` — `test_get_playlist_songs_returns_all_songs` asserts every added song is returned (would have failed against the `[:-1]` slice).
