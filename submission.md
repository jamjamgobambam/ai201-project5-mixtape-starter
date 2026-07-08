# Mixtape — Codebase Map

> Project 5 submission — Carlos Salcedo · branch `bugfix/mixtape`

Mixtape is a Flask + SQLAlchemy JSON API for a social music app. Users share songs,
listen to them, rate them, build collaborative playlists, keep listening streaks, and
watch what friends are playing through two feeds. There's no frontend — every response
is JSON.

---

## AI Usage

I used an AI assistant as a guide for understanding an unfamiliar codebase, not as a
substitute for doing the debugging myself. Concretely:

- **Understanding the architecture and routing.** Early on I asked the AI to explain how
  the app was laid out and to trace the flow of a request from an endpoint down to where the
  work actually happens. That's where it was most useful — it made the `routes/` →
  `services/` → `models.py` layering click, and showed me that every route is a thin
  pass-through that immediately delegates to one service function. Once I understood that
  pattern, I could follow any feature (e.g. `GET /playlists/<id>/songs` →
  `get_playlist_songs()`) straight to the service where the logic lived.

- **Tracing to the right file, then finding the bug myself.** For each issue I used the
  README's "affected service" mapping plus the routing understanding above to narrow down
  where to look. From there I read the service functions and found the actual defects on my
  own — the stray `songs[:-1]` slice in the playlist service, the `weekday() != 6` clause in
  the streak logic, and the oversized 24-hour window in the feed. I'd explain to Claude what I thought the bug was and why, and it helped me check my reasoning against the code and the expected behavior before I changed anything.

- **Reproducing bugs without a frontend.** Since this is a JSON API with no UI, I had the AI
  help me figure out the terminal steps to confirm each bug — seeding the DB, hitting the
  endpoints, and comparing actual vs. expected output — so I could see each failure before
  and after the fix rather than assuming.

**Where I had to verify things myself / where the AI fell short.** I didn't take
explanations at face value — I confirmed behavior by running `seed_data.py`, hitting the
endpoints, and running `pytest`. That mattered: for the search-duplication issue (#3), the
AI's first explanation was incomplete. It described the `outerjoin` as producing visible
duplicate rows, but when I actually ran the search it returned a single result — the
duplicates were being silently collapsed by SQLAlchemy's legacy query de-duplication. Only
by running it did the real picture emerge (the bug is latent rather than currently visible),
which changed how that issue should be handled. The AI also initially leaned on a
"sharing a song sends a notification" example that turned out not to exist in this code —
sharing notifies no one — so I corrected the data-flow write-up to match what the code
actually does. The takeaway: the AI was a strong tool for orientation and for pressure-testing
my own conclusions, but the confidence in each fix came from reproducing and testing it
myself.

---

## 1. What each piece is responsible for

The app is three layers: **routes** parse/format HTTP, **services** hold all logic and
DB access, **models** define the schema. The `db = SQLAlchemy()` object is created once
in [app.py](app.py) and imported everywhere.

### Top level

- **[app.py](app.py)** — the application factory (`create_app`). Owns the shared `db`
  instance, configures SQLite (`DATABASE_URL` env override), registers the four
  blueprints under `/songs`, `/playlists`, `/users`, `/feed`, and runs `db.create_all()`
  inside the app context. Config can be overridden at construction (the tests pass
  `TESTING` + an in-memory URI this way).
- **[models.py](models.py)** — all 7 models + 3 association tables (details in §3). Each
  model owns its own `to_dict()`, so serialization is a model concern, not a route one.
- **[seed_data.py](seed_data.py)** — rebuilds the DB and loads 5 users, 25 songs (grouped
  into 0-tag / 1-tag / 3+-tag sets on purpose), 3 playlists, two weeks of listening
  events, streaks, and a sample notification. The grouping isn't incidental — the 3+-tag
  songs are seeded specifically to expose the search-duplication bug.

### `routes/` — HTTP layer (four blueprints)

Every route follows the same shape: read the request, call one service function, catch
`ValueError` → 400/404, `jsonify` the result. No business logic.

- **[routes/songs.py](routes/songs.py)** — `GET /search`, `GET /<id>`, `POST /<id>/rate`,
  `POST /<id>/listen`.
- **[routes/playlists.py](routes/playlists.py)** — `POST /`, `GET /<id>`,
  `GET /<id>/songs`, `POST /<id>/songs`.
- **[routes/users.py](routes/users.py)** — `GET /<id>`, `GET /<id>/streak`,
  `GET /<id>/notifications` (with `?unread_only=`), `POST /notifications/<id>/read`.
- **[routes/feed.py](routes/feed.py)** — `GET /<user_id>/listening-now` and
  `GET /<user_id>/activity`.

### `services/` — business logic

- **[services/search_service.py](services/search_service.py)** — `search_songs()` does a
  case-insensitive `ILIKE` on title/artist; `get_song()` fetches one by id.
- **[services/streak_service.py](services/streak_service.py)** — `record_listening_event()`
  writes a `ListeningEvent` and then calls `update_listening_streak()`, which is the
  consecutive-calendar-day logic (increment if yesterday, reset if a day was skipped).
- **[services/feed_service.py](services/feed_service.py)** — `get_friends_listening_now()`
  (24h window, de-duped to one entry per friend) and `get_activity_feed()` (latest 20,
  no window, no de-dup).
- **[services/notification_service.py](services/notification_service.py)** —
  `create_notification()`, `get_notifications()`, `mark_as_read()`, `rate_song()`, and
  `add_to_playlist()` (which both attaches the song *and* fires a notification).
- **[services/playlist_service.py](services/playlist_service.py)** — create/read
  playlists and return their songs **ordered by `position`**.

### `tests/`

Pytest with an in-memory SQLite fixture (`create_app({"TESTING": True, ...})`):
[test_playlists.py](tests/test_playlists.py), [test_search.py](tests/test_search.py),
[test_streaks.py](tests/test_streaks.py).

---

## 2. The data model (things that aren't obvious from the file tree)

[models.py](models.py) defines 7 models. The details that matter:

- **User** — friendship is a *self-referential* many-to-many via the `friendships` table,
  loaded `lazy="dynamic"`. It's not automatically symmetric: `seed_data.py` inserts both
  `(a→b)` and `(b→a)` rows by hand, so "friends" is only mutual because the seed makes it
  so. `User.to_dict()` deliberately omits `email`.
- **Song** — carries `shared_by` (FK to the sharer), `share_note`, and a many-to-many to
  **Tag** (`lazy="subquery"`). `to_dict()` flattens tags to a list of name strings.
- **Rating** — *is* a separate model (unlike some designs where the score lives on the
  song). A `UniqueConstraint(user_id, song_id)` enforces one rating per user per song, and
  `rate_song()` honors that by updating the existing row instead of inserting a duplicate.
- **Playlist ↔ Song via `playlist_entries`** — the interesting join table. It adds three
  columns beyond the two FKs: **`position`** (explicit ordering — songs have a defined
  place, not just insertion order), **`added_by`**, and **`added_at`**. So the schema
  records who added each song, when, and in what order.
- **ListeningEvent** — one row per listen; the raw feedstock for both the feeds and the
  streak calculation.
- **Notification** — a per-user message with a `notification_type` string and a `read`
  flag. Delivery is pull-based (no push).

`song_tags` is a plain two-column join table; `friendships` and `playlist_entries` are the
two that carry meaning beyond membership.

---

## 3. Data flow — a friend adds your song to a playlist → you get notified

I traced this one because the notification path is the most cross-cutting feature.
(Note: *sharing* a song does **not** notify anyone, and — see below — neither does
*rating*, even though you'd expect it to. The one path that fires a notification is the
playlist-add.)

**Request:** `POST /playlists/<playlist_id>/songs` with `{"song_id", "added_by"}`.

1. **[routes/playlists.py:43 `add_song()`](routes/playlists.py#L43)** — pulls `song_id`
   and `added_by`, 400s if either is missing, then calls the service.
2. **[notification_service.py:35 `add_to_playlist()`](services/notification_service.py#L35)**
   — loads the `Song`, adding `User`, and `Playlist` (each missing one → `ValueError` →
   400); appends to `playlist.songs` and commits (this writes the `playlist_entries` row).
3. **The rule:** only if `song.shared_by != added_by` (you didn't add your own song) does
   it call **[create_notification()](services/notification_service.py#L13)**, targeting
   `song.shared_by` with type `"song_added_to_playlist"`.
4. **Later, pull-based:** the sharer reads it via `GET /users/<id>/notifications`
   → [users.py:29](routes/users.py#L29) → [get_notifications()](services/notification_service.py#L113).

```
POST /playlists/<id>/songs
   → routes/playlists.py  add_song()              (parse + validate)
   → notification_service.add_to_playlist()       (attach song, commit playlist_entries row)
        └─ if song.shared_by != added_by:
   → notification_service.create_notification()    (insert Notification for the sharer)
   … later …
   → GET /users/<id>/notifications                 (sharer polls; nothing is pushed)
```

**What reading the code revealed:** the parallel action `rate_song()`
([notification_service.py:73](services/notification_service.py#L73)) validates the score,
upserts the `Rating`, and commits — but it **never calls `create_notification()`**. So
rating a friend's song silently produces no notification. That asymmetry with
`add_to_playlist()` is one of the reported bugs, not intended behavior.

---

## 4. Patterns in how the app is organized

- **Strict route → service → model layering.** Every route delegates immediately to one
  service function; routes only parse input and format the response, and all business
  logic and DB access live in `services/`. Serialization is pushed down further, into each
  model's `to_dict()`.
- **`ValueError` is the error contract.** Services raise `ValueError("… not found")`;
  routes catch it and map to 400/404. There's no custom exception type — the message
  string *is* the API error body.
- **One shared `db` from the factory** — the standard Flask app-factory pattern, which is
  what lets the tests spin up an isolated in-memory instance per run.
- **Association tables carry domain metadata**, not just FKs (`playlist_entries` →
  position/added_by/added_at). The model captures history, not only current state.
- **Notifications are pull-based** — recipients poll an endpoint; there's no push channel.
- **Deferred imports to dodge circular deps** — `add_to_playlist()` imports `Playlist` and
  `playlist_service` *inside* the function because those modules import back into the
  notification service.
- **Timestamps intend to be UTC-aware** (`datetime.now(timezone.utc)`), but SQLite stores
  them naive — a detail that matters to the feed's time-window comparison.

---

## Root Cause Analyses

### Bug #1

**Issue number and title.** Issue #1 — "My listening streak keeps resetting"
(affected service: **streak_service.py**).

**How I reproduced it.** This one is time-dependent, so it can't be reproduced through the
`POST /songs/<id>/listen` endpoint on an arbitrary day — the endpoint stamps the event with
the real `datetime.now()`, so the buggy branch only fires when the real-world "today" is a
Sunday. To trigger it on demand I called the underlying logic directly with a crafted date:
seed a user with an existing streak (say 5) whose `last_listened_at` is a Saturday, then call
`update_listening_streak(user, now)` with `now` set to the following Sunday
(`datetime(2026, 7, 12, ...)` is a Sunday). Even though Saturday → Sunday is a perfectly
consecutive day, the streak came back as 1 instead of 6. Running the same setup with
`now` on any non-Sunday returned 6, which isolated the trigger condition to "today is a
Sunday" — matching the report that the streak "keeps resetting" (it dies every week when the
user listens on a Sunday).

**How I found the root cause.** The README maps issue #1 to streak_service.py, and the
only function that changes the streak value is `update_listening_streak()`, so I read that
directly with the question "what could reset a streak on a specific day of the week?" in
mind. The function computes `days_since_last = (today - last_date).days` and then branches:
`== 0` no-ops, `== 1` should increment, everything else resets. The increment branch read
`elif days_since_last == 1 and today.weekday() != 6:`. The `today.weekday() != 6` clause is
the part with no business justification — nothing else in the function treats a particular
weekday specially — so it stood out immediately. Recalling that Python's `datetime.weekday()`
returns `6` for Sunday (Monday = 0 … Sunday = 6), I could see that on Sundays the compound
condition is false, so a consecutive-day listen skips the increment and falls through to the
`else`, which resets the streak to 1. That was the moment of certainty: the extra clause was
routing valid consecutive days into the reset branch, but only on Sundays.

**The root cause.** Python's `datetime.weekday()` numbers days Monday = 0 through Sunday = 6.
The increment branch was guarded by `days_since_last == 1 and today.weekday() != 6`, which
means "increment only if the last listen was yesterday and today is not Sunday." There is
no reason a Sunday should break an otherwise-consecutive streak, so the `and today.weekday()
!= 6` clause was simply wrong and not needed: whenever a user listened on consecutive days and the second day
happened to be a Sunday, the `== 1` case evaluated to false, control fell through to the
`else`, and the streak was reset to 1 instead of incremented. A daily listener therefore lost
their streak every Sunday.

**Your fix and side-effect check.** Removed the weekday clause so the branch reads
`elif days_since_last == 1:` and increments on any consecutive day. The `else` is deliberately
kept, it still handles the genuine reset case (`days_since_last > 1`, a day was
skipped). This fixes the root cause because the only thing wrong was consecutive Sundays being
mis-routed into the reset branch; with the clause gone, day-of-week no longer affects the
calculation at all. To confirm I didn't break the other branches, I re-ran the logic across
every case: consecutive day on a Sunday → 6 (now correct), consecutive day on a weekday → 6,
same-day repeat listen → unchanged, a 2-day gap → reset to 1, and first-ever listen → 1. All
five behaved as expected, and the existing `pytest tests/test_streaks.py` suite still passes
(5 passed). The `record_listening_event()` caller is unaffected since it only depends on the
streak being updated in place, which still happens.

### Bug #2

**Issue number and title.** Issue #2 — "Friends Listening Now shows people from yesterday"
(affected service: **feed_service.py**).

**How I reproduced it.** I seeded the DB with `python seed_data.py` and hit
`GET /feed/<user_id>/listening-now` for a user with friends. The seed plants two kinds of
listening events: a few from the past ~10–20 minutes and a batch of older
ones from several hours to two weeks ago. The endpoint returned friends whose most recent
listen was many hours old reading the `listened_at` timestamp on each returned entry
showed times well outside anything you'd call "listening now." To pin the boundary cleanly I
also ran the service in isolation with two friends: one who listened 20 minutes ago and one
who listened 20 hours ago (yesterday). Both came back in the feed, confirming the window
was far too wide.

**How I found the root cause.** The README maps issue #2 to feed_service.py, so I opened
it and looked at `get_friends_listening_now()`, the function behind the endpoint. Its query
filters events with `ListeningEvent.listened_at >= cutoff`, where
`cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD`. That made the whole behavior hinge
on one value, so I traced `RECENT_THRESHOLD` to the top of the module and found it defined as
`timedelta(hours=24)`. That was the moment it clicked: a 24-hour rolling window means the feed
counts anything within the last full day as "listening now," which is exactly why someone who
listened 20 hours ago (yesterday) still appears. Nothing was wrong with the query, the
friend lookup, or the dedup — the threshold constant itself encoded the wrong definition of
"now."

**The root cause.** "Friends Listening Now" is meant to show who is playing something right
now, but the recency window was set to `RECENT_THRESHOLD = timedelta(hours=24)`. A 24-hour
rolling window admits every listen from the past full day, so a friend who last listened many
hours ago — including yesterday — still satisfies `listened_at >= cutoff` and shows up in the
feed. The bug is not in the filtering logic but in the size of the window: 24 hours is far
too long to represent "now."

**Your fix and side-effect check.** Changed the constant to
`RECENT_THRESHOLD = timedelta(minutes=30)`. Thirty minutes matches the app's own intent — the
seed file explicitly labels its ~10–20-minute-old events as the ones that "should appear in
listening now," while the events it expects to be excluded start at two hours out — so the new
window cleanly separates the two. I re-checked the isolated two-friend case: the 20-minute
friend still appears and the 20-hour (yesterday) friend no longer does. This fixes the root
cause because the filter was always correct; only the window it compared against was wrong.
I confirmed the other feed function, `get_activity_feed()`, is unaffected — it intentionally
ignores `RECENT_THRESHOLD` entirely and just returns the most recent 20 events regardless of
age, so shrinking the window changes only the "listening now" feed as intended. (One known
limitation I did not change: `listened_at` is stored naive by SQLite while `cutoff` is
UTC-aware, so the comparison relies on both effectively being UTC. That's a pre-existing
concern independent of the window size.)

### Bug #5

**Issue number and title.** Issue #5 — "The last song in a playlist never shows up"
(affected service: **playlist_service.py**).

**How I reproduced it.** No custom test data was needed — the repo ships with
**seed_data.py**, which preloads playlists that each already contain several songs. I ran
`python seed_data.py` to populate the DB, then hit `GET /playlists/<id>/songs` on a seeded
playlist and compared the returned `count` against the number of songs actually seeded into
it. The "Late Night Vibes" playlist is loaded with 7 songs, but the endpoint reported
`"count": 6`. The miss is always the last (highest-`position`) song,
never a random one which told me this was an ordering-dependent off-by-one error.

**How I found the root cause.** The README maps issue #5 to playlist_service.py, so I
already had that file and this specific bug in mind as I traced the request in. I was reading with "where could the *last* item get dropped?" as the
question. I followed the call chain `GET /playlists/<id>/songs` → routes/playlists.py
`get_songs()` → playlist_service.py `get_playlist_songs()`. The route was a pure
pass-through (it only wraps the list in `{"songs", "count"}`), so a count short by exactly
one had to come from the service. Reading `get_playlist_songs()` top to bottom, the query
looked correct — it joins `playlist_entries`, filters by playlist, and orders by
`asc(position)`, so the list it built was complete and correctly ordered. Then I hit the
`return` line, and with the "last song is missing" symptom already front of mind the
`songs[:-1]` slice jumped out immediately. The docstring right above it even
promises it returns all songs in the playlist which this splicing doesn't show so I knew this was the issue.

**The root cause.** Python's `list[:-1]` slice returns every element except the last one.
`get_playlist_songs()` had already run a correct query that returned the playlist's songs
ordered by ascending `position`, but the final list comprehension iterated over `songs[:-1]`
instead of `songs`. Because the list was sorted ascending, the dropped element was always
the song with the highest `position`. This is always the last added track so the last song never shows up.

**Your fix and side-effect check.** Changed line 66 from
`return [song.to_dict() for song in songs[:-1]]` to
`return [song.to_dict() for song in songs]`, removing the truncation so the comprehension
walks the full ordered result. This fixes the root cause directly: the query was always
correct, so iterating the complete list instead of a one-short slice returns every song.
After the change: my reproduction returned all 5 songs in order, and
`GET /playlists/<id>/songs` on the seeded playlist reported the full count. I then ran the
existing suite — `pytest tests/test_playlists.py` (3 passed) — to confirm playlist creation
and retrieval still behave, and re-checked that the other service that mutates playlists,
`add_to_playlist()` in `notification_service.py`, was unaffected since it appends to
`playlist.songs` and never calls `get_playlist_songs()`. No ordering or pagination logic
depends on the old behavior, so removing the slice has no downstream effects.
