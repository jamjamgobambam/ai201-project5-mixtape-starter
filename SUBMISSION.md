# Mixtape Bug Hunt — Submission

## AI Usage

I used Cursor (AI) throughout this project, primarily for **codebase navigation and debugging support** — not for writing fixes blindly. Below is an honest account of what worked, what didn't, and what I still had to verify myself.

### Codebase orientation (Milestone 1)

- **Asked AI:** "What modules handle interactions between files in this repo?" and "How does the rating flow work end-to-end?"
- **What it helped with:** Quickly mapped the `routes/` → `services/` → `models.py` layering and identified that bugs live in `services/`. Suggested tracing features from routes downward rather than jumping straight into service files.
- **What I verified myself:** Read `app.py`, `models.py`, and each route file to confirm the call chains. Used `pydeps app.py` to generate an import diagram (had to work around the hyphenated folder name by running from inside the project).
- **Where AI was incomplete:** AI initially suggested `pipdeptree` for internal module interactions — that's for installed packages, not app file structure. I switched to reading imports with `grep` and `pydeps`.

### Bug reproduction (Milestone 2)

- **Asked AI:** How to run failing tests against unfixed code; whether seed data contained the right conditions for each bug.
- **What it helped with:** Identified that Issue #1 needs Saturday→Sunday dates, Issue #3 is conditional on multi-tag songs, and Issue #4's hint points to comparing two functions in the same file.
- **What I verified myself:** Checked out `main` branch service files and ran `pytest` to confirm failures before writing any fix. For Issue #3, AI's initial claim that duplicates appear in `search_songs()` return values didn't reproduce with SQLAlchemy 2.x — I had to run `.count()` on the raw query to see 3 SQL rows for a 3-tag song vs 1 for a 0-tag song. The bug is real at the SQL level even when ORM deduplication masks it in some cases.

### Investigation and debugging (Milestone 3)

| Bug | What I asked AI | What AI got right | What I had to verify myself |
|-----|-----------------|-------------------|----------------------------|
| #1 Streak | "What does `weekday()` return for Sunday?" | Returns `6`; the `!= 6` guard blocks Sunday increments | Ran `test_streak_increments_on_sunday` — failed on `main`, passed after fix |
| #2 Feed | "Why would a 24-hour window show stale listeners?" | Threshold too wide for "listening now" | Built minimal repro with 15-min vs 5-hour events; confirmed both appeared with 24h window |
| #3 Search | "Why would duplicates be conditional?" | Join on `song_tags` multiplies rows per tag | Ran `.count()` on query — 3 rows for 3-tag song, 1 for 0-tag song |
| #4 Notifications | "What's different between the two code paths?" | `add_to_playlist` calls `create_notification`, `rate_song` doesn't | Read both functions line-by-line in `notification_service.py`; called `rate_song` + `get_notifications` to confirm empty result |
| #5 Playlist | Nothing — obvious from test failure | N/A | Test output showed 4 songs returned for 5-song playlist; found `songs[:-1]` in return statement |

### What I did NOT use AI for

- Choosing the fix itself — each fix was one targeted line or small block after I read the code
- Committing without running tests — always ran `pytest tests/` after each fix
- Skipping reproduction — every bug was confirmed on `main` before fixing

### Workflow that worked

```
Reproduce on main → read the service file → form hypothesis → verify with test/shell → fix → pytest → document → commit
```

AI was most useful **after** I found the suspicious code, not before. Asking "where is the bug?" before reading the relevant file tended to produce plausible but wrong answers.

---

## Codebase Map

### Main files and roles

| File / directory | Role |
|------------------|------|
| `app.py` | Flask app factory; initializes SQLAlchemy (`db`), registers route blueprints, creates tables on startup |
| `models.py` | SQLAlchemy models (`User`, `Song`, `Playlist`, `ListeningEvent`, `Rating`, `Notification`, `Tag`) and association tables (`friendships`, `song_tags`, `playlist_entries`) |
| `routes/` | HTTP layer — parses requests, calls services, returns JSON |
| `services/` | Business logic — where all five bugs live |
| `seed_data.py` | Populates the SQLite DB with users, songs, playlists, and sample events |
| `tests/` | Pytest suite covering streaks, search, playlists, and feed |

### Feature data flow: rating a song

1. Client sends `POST /songs/<song_id>/rate` with `{ "user_id", "score" }`
2. `routes/songs.py` validates input and calls `notification_service.rate_song()`
3. `rate_song()` loads the `Song` and `User`, upserts a `Rating` row, commits
4. If the rater is not the original sharer, `create_notification()` notifies `song.shared_by`
5. Client can fetch notifications via `GET /users/<user_id>/notifications`

### Layering

```
routes/  →  services/  →  models.py + app.db
```

Routes should stay thin; persistence and rules live in services.

---

## Milestone 4: Final Review

### Commit history (`git log --oneline bugfix/mixtape`)

```
0d54b84 docs: add Milestone 3 full root cause analyses for all five bugs
55f7d60 docs: add Milestone 2 bug reproduction steps to submission
5e7e8cd docs: add bug hunt submission with codebase map and root cause analyses
fac6337 test: add regression test for Friends Listening Now recency filter
9099728 fix: return all playlist songs including the last entry
6b2192e fix: notify song sharer when a friend rates their song
c61497b fix: deduplicate search results when songs have multiple tags
3a5b1ca fix: narrow Friends Listening Now window to exclude stale events
d4cebf0 fix: remove Sunday boundary that incorrectly resets listening streak
2dfdeaa Add .gitignore file and update README with setup instructions
7b64551 initial commit
```

**Review:** Five separate `fix:` commits — one per bug. No bundled fixes. Docs and test commits are separate.

![git log --oneline bugfix/mixtape](ss_gitlog.png)

### RCA completeness check

| Bug | Title | Reproduced | Found cause | Root cause | Fix + side effects |
|-----|-------|:---:|:---:|:---:|:---:|
| #1 | Streak resets on Sunday | ✅ | ✅ | ✅ | ✅ |
| #2 | Stale "listening now" | ✅ | ✅ | ✅ | ✅ |
| #3 | Search duplicates | ✅ | ✅ | ✅ | ✅ |
| #4 | Missing rating notification | ✅ | ✅ | ✅ | ✅ |
| #5 | Last playlist song missing | ✅ | ✅ | ✅ | ✅ |

### Test verification

```
pytest tests/  →  14 passed
```

---

## Root Cause Analyses

All five bugs fixed on branch `bugfix/mixtape`, one commit each.

---

### Issue #1 — My listening streak keeps resetting

**How I reproduced it**

1. Checked out unfixed `services/streak_service.py` from `main`.
2. Ran `pytest tests/test_streaks.py::test_streak_increments_on_sunday -v`.
3. Test calls `update_listening_streak(user, saturday)` → streak = 1, then `update_listening_streak(user, sunday)` → **expected 2, got 1**.
4. Confirmed Mon→Tue still increments (`test_streak_increments_on_consecutive_day` passes) — failure is specific to Sunday as the second day.

**How I found the root cause**

1. README pointed to `streak_service.py` for Issue #1.
2. Traced from symptom: streak resets → `routes/songs.py` `POST /listen` → `record_listening_event()` → `update_listening_streak()`.
3. Read `update_listening_streak()` in `services/streak_service.py` lines 70–76.
4. The consecutive-day branch was `elif days_since_last == 1 and today.weekday() != 6` — the extra `weekday() != 6` guard was the only path-specific to Sunday.
5. Confident moment: when `days_since_last == 1` on Sunday, `weekday()` returns `6`, the condition is `False`, execution falls to `else` which sets `listening_streak = 1`.

**The root cause**

`datetime.weekday()` returns `6` for Sunday. The streak increment branch required `days_since_last == 1 and today.weekday() != 6`, so a user who listened yesterday (Saturday, `days_since_last == 1`) and listens again today (Sunday) failed the increment check and hit the reset branch instead. The code treated Sunday as a non-consecutive day even when only one calendar day had passed.

**Fix and side-effect check**

- **Change:** Removed `and today.weekday() != 6` so `days_since_last == 1` always increments.
- **Why it works:** Streak logic now depends only on calendar-day gap, not weekday name.
- **Side effects checked:** Ran full `tests/test_streaks.py` — new-user start, consecutive days, same-day no double-count, skipped-day reset, and Sunday increment all pass.
- **Commit:** `d4cebf0` — `fix: remove Sunday boundary that incorrectly resets listening streak`

---

### Issue #2 — Friends Listening Now shows people from yesterday

**How I reproduced it**

1. On `main`, created `nova` with friends `darius` (listened 15 min ago) and `simone` (listened 5 hours ago).
2. Called `get_friends_listening_now(nova.id)` → returned **both** friends.
3. Confirmed with `python seed_data.py`: seed comments say events at 10–20 min should appear but events at 2–18 hours should not; with the 24-hour threshold, stale friends appeared.

**How I found the root cause**

1. README → `feed_service.py` for Issue #2.
2. Traced: `GET /feed/<user_id>/listening-now` → `routes/feed.py` → `get_friends_listening_now()`.
3. Read `RECENT_THRESHOLD = timedelta(hours=24)` and filter `ListeningEvent.listened_at >= cutoff`.
4. Compared with `seed_data.py` lines 111–130 — "recent" events are minutes old; "older" events start at 2 hours ago, all within 24 hours.
5. Confident moment: the threshold name says "listening **now**" but the window was a full day, so hours-old listens qualified.

**The root cause**

`RECENT_THRESHOLD` was `timedelta(hours=24)`. The filter `listened_at >= now - 24 hours` included any friend who listened within the past day, including people who listened 5–18 hours ago. For a "listening now" feed, that window is far too wide and surfaces yesterday's activity alongside genuinely current listeners.

**Fix and side-effect check**

- **Change:** `RECENT_THRESHOLD = timedelta(minutes=30)` to align with seed-data intent (recent events at 10–20 min).
- **Why it works:** Only events within the last 30 minutes pass the filter; 2+ hour old events are excluded.
- **Side effects checked:** `get_activity_feed()` is a separate function with no recency filter — unchanged and still returns historical events. Added `tests/test_feed.py::test_listening_now_excludes_stale_events` as regression coverage.
- **Commit:** `3a5b1ca` — `fix: narrow Friends Listening Now window to exclude stale events`

---

### Issue #3 — The same song keeps showing up twice in search

**How I reproduced it**

1. On `main`, created "Crown Heights Anthem" with 3 tags (`rap`, `hip-hop`, `boom bap`) and "Midnight Drive" with 0 tags.
2. Ran the raw query from `search_songs`: `db.session.query(Song).outerjoin(song_tags, ...).filter(title ilike '%Crown Heights%')`.
3. `.count()` returned **3** for the 3-tag song, **1** for the no-tag song — duplicates are conditional on tag count.
4. `tests/test_search.py::test_search_no_duplicates_multi_tag_song` documents expected behavior (1 result, not 3).

**How I found the root cause**

1. README → `search_service.py` for Issue #3; hint said duplicates are conditional.
2. Traced: `GET /songs/search?q=...` → `routes/songs.py` → `search_songs()`.
3. Read the query: filters on `Song.title` / `Song.artist` but also `outerjoin(song_tags)` — the join is unnecessary for the filter and multiplies rows.
4. Checked `models.py` `song_tags` association table — one row per tag per song.
5. Confident moment: a song with N tags produces N joined rows in SQL; without deduplication the result set has one entry per tag.

**The root cause**

`search_songs()` joins `song_tags` via `outerjoin` even though the search filter only uses `Song.title` and `Song.artist`. Each tag association adds another row to the SQL result for the same `Song`. Songs with 0–1 tags return one row; songs with 3 tags return 3 rows for the same song. The bug is conditional — it only manifests for multi-tag songs.

**Fix and side-effect check**

- **Change:** Added `.distinct()` before `.all()` on the query.
- **Why it works:** Collapses duplicate `Song` rows from the join into one result per song.
- **Side effects checked:** Ran full `tests/test_search.py` — matching, no-match, and no-duplicate tests for 0-tag, 1-tag, and 3-tag songs all pass. `get_song()` is unaffected.
- **Commit:** `c61497b` — `fix: deduplicate search results when songs have multiple tags`

---

### Issue #4 — Notified on playlist add but not on rating

**How I reproduced it**

1. On `main`, created `nova` (sharer) and `darius` (rater), song owned by `nova`.
2. Called `rate_song(darius.id, song.id, 5)` then `get_notifications(nova.id)` → **empty list**.
3. Seed data already has a working `song_added_to_playlist` notification for `nova`, proving the notification system works.

**How I found the root cause**

1. README → `notification_service.py`; hint said compare working notification pattern line-by-line.
2. Traced rating path: `POST /songs/<id>/rate` → `routes/songs.py` → `rate_song()`.
3. Traced playlist path: `routes/playlists.py` → `add_to_playlist()` in the same file.
4. `add_to_playlist()` lines 64–70: after saving, checks `song.shared_by != added_by_user_id` and calls `create_notification()`.
5. `rate_song()` lines 96–108: saves rating, commits, returns — **no notification call anywhere**.
6. Confident moment: same file, same pattern needed, one code path has it and the other doesn't. Architectural omission, not a typo.

**The root cause**

`rate_song()` persisted the rating correctly but never called `create_notification()`. The playlist-add flow in the same service file already had the correct pattern: after the DB write, if the acting user is not the song sharer, notify `song.shared_by`. The rating flow was missing this entire notification step, so sharers never learned when a friend rated their song.

**Fix and side-effect check**

- **Change:** After `db.session.commit()`, added the same guard and `create_notification()` call with type `song_rated`.
- **Why it works:** Mirrors the proven `add_to_playlist()` pattern in the same service.
- **Side effects checked:** Self-ratings (`user_id == song.shared_by`) correctly skip notification. `get_notifications()` and `mark_as_read()` unchanged. Playlist notification path untouched.
- **Commit:** `6b2192e` — `fix: notify song sharer when a friend rates their song`

---

### Issue #5 — The last song in a playlist never shows up

**How I reproduced it**

1. On `main`, ran `pytest tests/test_playlists.py::test_playlist_returns_all_songs -v`.
2. Test seeds a playlist with 5 songs at positions 1–5.
3. `get_playlist_songs()` returned **4 songs** — `Track 5` missing.
4. `test_playlist_returns_songs_in_order` also failed (titles ended at `Track 4`).

**How I found the root cause**

1. README → `playlist_service.py` for Issue #5.
2. Traced: `GET /playlists/<id>/songs` → `routes/playlists.py` → `get_playlist_songs()`.
3. Read the function: query joins `playlist_entries`, orders by `position`, fetches all songs correctly.
4. Line 66 (buggy): `return [song.to_dict() for song in songs[:-1]]` — Python slice `[:-1]` excludes the last element.
5. Confident moment: the query returned 5 songs; only the return statement discarded the last one. Off-by-one at the slice, not in the query.

**The root cause**

`get_playlist_songs()` correctly queried and ordered all songs in the playlist, but the return statement used `songs[:-1]`, which slices off the final list element. A playlist with N songs always returned N−1. The last song by position was consistently dropped regardless of which song it was.

**Fix and side-effect check**

- **Change:** `return [song.to_dict() for song in songs]` — removed `[:-1]`.
- **Why it works:** Returns the full query result without truncating.
- **Side effects checked:** `test_playlist_returns_all_songs` (5 songs), `test_playlist_returns_songs_in_order`, and `test_empty_playlist_returns_empty_list` all pass. `get_playlist()` and `create_playlist()` unchanged.
- **Commit:** `9099728` — `fix: return all playlist songs including the last entry`

---

## Milestone 4 Checkpoint

| Requirement | Status |
|-------------|--------|
| `git log` — ≥ 3 separate `fix:` commits | ✅ 5 fix commits |
| All RCA entries complete (5 fields each) | ✅ |
| AI usage section at top of doc | ✅ |
| All tests pass | ✅ 14/14 |
| Regression test (stretch) | ✅ `tests/test_feed.py` |
