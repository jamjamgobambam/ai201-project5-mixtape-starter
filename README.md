# Mixtape

A social music app where friends share songs, build collaborative playlists, and track listening stats.

This is the starter repo for **Project 5: Mixtape Bug Hunt**. The app has five open issues in its tracker. Your job is to find, fix, and document at least three of them.

---

## App Structure

```
ai201-project5-mixtape-starter/
├── app.py                      # Flask app factory and DB setup
├── models.py                   # SQLAlchemy models for all entities
├── routes/
│   ├── songs.py                # Song sharing, search, and rating routes
│   ├── playlists.py            # Playlist creation and song management
│   ├── users.py                # User profiles, streaks, notifications
│   └── feed.py                 # Friends listening now, activity feed
├── services/
│   ├── streak_service.py       # Listening streak logic
│   ├── feed_service.py         # Friends listening now feed logic
│   ├── search_service.py       # Song search logic
│   ├── notification_service.py # Notification creation and retrieval
│   └── playlist_service.py     # Playlist retrieval logic
├── tests/
│   ├── test_streaks.py
│   ├── test_search.py
│   └── test_playlists.py
├── seed_data.py                # Populates DB with test data
├── requirements.txt
└── .gitignore
```

The bugs live in the `services/` layer. The routes call services — if something is broken in an endpoint, trace it back to the service it calls.

---

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows (Command Prompt)
.venv\Scripts\activate.bat

# Windows (Git Bash)
source .venv/Scripts/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Seed the database with test data:

```bash
python3 seed_data.py
```

Run the app:

```bash
FLASK_APP=app:create_app flask run
```

> **macOS note:** If the app starts but requests hang or return connection refused, try `http://127.0.0.1:5000` instead of `http://localhost:5000`. On macOS, `localhost` sometimes resolves to an IPv6 address that Flask isn't listening on.

Run tests:

```bash
pytest tests/
```

---

## The Five Open Issues

| # | Title | Affected service |
|---|-------|-----------------|
| 1 | My listening streak keeps resetting | `streak_service.py` |
| 2 | Friends Listening Now shows people from yesterday | `feed_service.py` |
| 3 | The same song keeps showing up twice in search | `search_service.py` |
| 4 | I got notified when a friend added my song to a playlist but not when they rated it | `notification_service.py` |
| 5 | The last song in a playlist never shows up | `playlist_service.py` |

Full issue descriptions are in the **Project 5 brief**. Read them carefully before opening any service file.

---

## How to Read the Code

Start with `models.py` to understand the data model. Then trace a feature through from its route to its service. For example:

- A user rates a song → `POST /songs/<song_id>/rate` → `routes/songs.py` → `notification_service.rate_song()`
- A user views a playlist → `GET /playlists/<id>/songs` → `routes/playlists.py` → `playlist_service.get_playlist_songs()`

Understanding the full call chain is part of the exercise — don't skip to the service file directly.

---

## Submission

Create a branch named `bugfix/mixtape` for your fixes. Each bug fix should be its own commit using conventional format:

```
fix: correct Sunday boundary condition in streak reset logic
```

See the project brief for full submission requirements.

### Issue #1 — My listening streak keeps resetting
**Reproduced:** Simulated consecutive daily listens across a week boundary (Sat → Sun) using [flask shell / direct DB inserts — fill in what you actually did]. Streak incremented correctly most days but reset to 1 specifically when the "today" listen fell on Saturday.

**How you found the root cause:** Traced the streak-check function called from the listen endpoint. Found a conditional `if today.weekday() != 5:` gating the increment path — this check has no relationship to "was yesterday's listen exactly one day ago," which is the only thing a daily-streak feature should be checking. Confirmed by testing: every weekday except Saturday incremented fine; Saturday always fell through to the reset branch regardless of whether the listen was actually consecutive.

**The root cause:** The increment logic was gated behind an unrelated day-of-week check (`today.weekday() != 5`) instead of checking whether the current listen date was exactly one calendar day after the last recorded listen date. On Saturday, a legitimate consecutive-day listen still failed the `!=5` condition, fell to the `else` branch, and reset the streak to 1 — regardless of actual consecutivity.

**Your fix and side-effect check:** Removed the weekday condition entirely and replaced it with a direct date-difference check: `(today - last_listen_date).days == 1` to increment, `== 0` to no-op (already listened today), anything else resets to 1. Verified by walking a full week of consecutive listens (Mon–Sun) and confirming the streak increments every single day with no drop, then confirmed a genuine skipped day still correctly resets to 1. *(AI use: used to confirm my read that the weekday condition had no logical basis in the feature and to reason through the correct date-comparison replacement; the faulty line itself was located independently.)*

---

### Issue #4 — I got notified when a friend added my song to a playlist but not when they rated it
**Reproduced:** Had one user add another user's shared song to a playlist — notification arrived as expected. Then had the same user rate a different song shared by the other user (POST /songs/<song_id>/rate) and checked GET /users/<user_id>/notifications — rating was saved on the song, but no notification was created.

**How you found the root cause:** Compared the two route handlers side by side — the playlist-add route and the rate route. The playlist-add route calls create_notification() after saving the playlist entry. The rate route saved the score to the Song record and returned, but never called create_notification() at all — there was no call to trace, not a broken one. Confirmed by reading through the entire rate handler function that no notification-related code existed anywhere in it.

**The root cause:** The rating endpoint was missing the call to create_notification() entirely. Unlike the playlist-add flow, which notifies the song's sharer as its last step, the rate flow saved the score and returned without ever constructing or persisting a Notification record. It wasn't a logic error in existing code — it was a missing step, architecturally inconsistent with the otherwise-consistent "action → notify" pattern used elsewhere in the notification service.

**Your fix and side-effect check:** Added a call to create_notification() in the rate route, guarded by `song.shared_by != user_id` so a user rating their own shared song doesn't get self-notified. The notification uses type "song_rated" and includes the rater's username, song title, and score. Verified: rating another user's song now produces exactly one notification; rating your own song produces none; the existing playlist-add notification still fires unaffected. *(AI use: used to help phrase the root cause precisely — distinguishing "a missing call" from "a broken call" — and to think through the self-notification guard condition before implementing it; the missing call itself was located independently by comparing the two routes.)*

---

### Issue #5 — The last song in a playlist never shows up
**Reproduced:** Opened a playlist reported to have 7 songs via GET /playlists/<playlist_id>/songs and counted only 6 returned. Added another song via POST /playlists/<playlist_id>/songs and re-fetched — the previously-missing song appeared, but the newly-added song was now missing instead, confirming the bug always hides exactly the most recently added song.

**How you found the root cause:** Traced the GET /playlists/<playlist_id>/songs route to the function building the response list. Found `return [song.to_dict() for song in songs[:-1]]` — a slice that drops the last element of the songs list before serializing it. Confirmed this was the cause by checking how `songs` was ordered upstream (by position/order), which meant "last in the list" always corresponded to "most recently added" — matching the exact symptom reported.

**The root cause:** The playlist songs endpoint sliced the ordered songs list with `songs[:-1]` before returning results, unconditionally dropping the last song in the list on every request. Since the list was ordered by add order/position, the last element was always the most recently added song, so it was silently excluded from every response regardless of playlist size.

**Your fix and side-effect check:** Changed `songs[:-1]` to `songs[:]` so all songs in the ordered list are included in the response. Verified by re-fetching the same playlist after the fix and confirming all 7 songs returned, then adding an 8th song and confirming all 8 appeared with none hidden — including immediately after the new add. *(AI use: used to confirm why this specific slice matched the reported symptom — that the newest song is always last in an order-sorted list, so the slice always dropped the most recent addition; the faulty line was located independently while reading the route.)*