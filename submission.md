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

### Issue #3 — The same song keeps showing up twice in search

**How I reproduced it.** This one was subtle and taught me not to trust a first read. Calling
`search_songs()` on a 3-tag song (e.g. `"Crown Heights Anthem"`, or by artist `"Static Era"`)
returned the song **once**, and the repo's own `test_search_no_duplicates_multi_tag_song`
*passed*. So at the public-API level the duplicate did not appear. To find where duplication
actually comes from, I ran the same query as a raw Core `select(...)` with `.scalars().all()`
(which does **not** de-duplicate): it returned **3 rows** for the 3-tag song and 3 for another
3-tag song — exactly one row per tag. So the duplication is real and lives in the query; it's
just being hidden.

**How I found the root cause.** `GET /songs/search` → `search_songs` in
`services/search_service.py`. The query does
`db.session.query(Song).outerjoin(song_tags, Song.id == song_tags.c.song_id).filter(title/artist ILIKE ...)`.
The `song_tags` association table has one row per (song, tag) pair, so a song with N tags
produces N joined rows. The confirming moment was comparing the raw `select` (3 rows) against
the service's `db.session.query(Song).all()` (1 row): SQLAlchemy 2.0's **legacy `Query` API
implicitly de-duplicates full-entity results by primary-key identity**, which is the *only*
reason the endpoint currently returns one row. The bug is latent — the join is a duplicate
generator that happens to be masked by an implicit ORM behavior.

**The root cause.** The `outerjoin(song_tags, ...)` is both **unnecessary and harmful**: tags
are not part of the search predicate (the `WHERE` only touches `Song.title`/`Song.artist`), and
`Song.to_dict()` already loads tags through the `tags` relationship. The join's sole effect is
to multiply result rows one-per-tag. Any change that removed the implicit de-dup — rewriting the
query with `select()` + `.scalars()`, adding `.count()`, paginating, or a future SQLAlchemy
version — would immediately surface the reported "same song twice (or three times)" behavior for
every multi-tag song.

**My fix and side-effect check.** I removed the `outerjoin(song_tags, ...)` entirely (and the now
unused `Tag`/`song_tags` imports), so the query filters on the `Song` table alone and can never
emit more than one row per song. This fixes the root cause instead of relying on implicit
de-dup. Side effects checked: (1) I confirmed search results **still include tags** — 
`search_songs("Crown")` returns `tags: ['rap', 'hip-hop', 'boom bap']` — because `to_dict()`
loads them via the relationship, not the join; (2) the matching logic is unchanged since the
join never contributed to the `WHERE`; (3) all 5 tests in `test_search.py` still pass, including
the no-duplicate tests for 0-, 1-, and 3-tag songs and the empty-result test. As an alternative I
considered `.distinct()`, but removing the pointless join addresses *why* duplication was
possible rather than papering over it.

### Issue #4 — Notified when a friend added my song to a playlist, but not when they rated it

**How I reproduced it.** Using seed data, `nova` rated a song shared by `simone` and I counted
`simone`'s notifications before and after: it stayed at **0** (expected 1). For contrast,
`add_to_playlist` in the same module *does* generate a notification, and the seed data even
pre-creates one "song added to playlist" notification — so the playlist path visibly works
while the rating path does not.

**How I found the root cause.** `POST /songs/<id>/rate` → `rate_song` in
`services/notification_service.py`. Following the hint that this is architectural, not a typo, I
compared `rate_song` line-by-line against its sibling `add_to_playlist` in the same file. Both
load the song, resolve the acting user, and mutate data — but `add_to_playlist` ends with an
`if song.shared_by != added_by_user_id: create_notification(...)` block, and `rate_song` simply
`return rating` with **no notification block at all**. The two functions live side by side, so
the omission is obvious once placed next to the working version.

**The root cause.** `rate_song` never calls `create_notification`. It's not a wrong argument or
a typo — the entire "notify the song's original sharer" step is missing from the rate flow,
even though the notification infrastructure (`create_notification`, the `Notification` model,
the `song_rated` type referenced in `create_notification`'s docstring) already exists and is
used by the playlist flow.

**My fix and side-effect check.** After the rating is committed, I added the same guarded
notification the playlist flow uses:
`if song.shared_by != user_id: create_notification(user_id=song.shared_by, notification_type="song_rated", body=f"{rater.username} rated your song '{song.title}' {score} stars.")`.
Side effects checked: (1) `rate_song` still returns the `Rating` object, so the route response is
unchanged; (2) the `song.shared_by != user_id` guard means rating **your own** song creates no
notification — I verified a self-rating leaves the count unchanged, matching how
`add_to_playlist` avoids self-notifying; (3) the rating upsert still works — re-rating updates
the existing score (protected by the `UniqueConstraint(user_id, song_id)`) and does not create
duplicate `Rating` rows; the notification is generated for the rating action regardless.

### Issue #5 — The last song in a playlist never shows up

**How I reproduced it.** The seeded playlist "Late Night Vibes" has **7** entries in
`playlist_entries`, but `get_playlist_songs()` returned only **6** song dicts. The repo's own
`test_playlist_returns_all_songs` (a 5-song playlist) failed asserting `len == 5` (got 4), and
`test_playlist_returns_songs_in_order` failed because `"Track 5"` was missing from the tail.

**How I found the root cause.** `GET /playlists/<id>/songs` → `get_playlist_songs` in
`services/playlist_service.py`. The query is correct — it joins `playlist_entries`, filters by
`playlist_id`, and orders by `asc(playlist_entries.c.position)`, so `songs` is the full, ordered
list. The bug is on the very last line: `return [song.to_dict() for song in songs[:-1]]`. The
`[:-1]` slice drops the final element. The function's own docstring ("returns **all** songs in
the playlist") contradicts the code, which confirmed the slice was the defect, not intended
behavior.

**The root cause.** The list slice `songs[:-1]` returns every element **except the last one**.
Because the query already orders by ascending position, "the last element" is always the
highest-position (most recently added) song — so the final song in every non-empty playlist was
silently omitted. It also means a 1-song playlist returned an empty list.

**My fix and side-effect check.** I changed `songs[:-1]` to `songs`, so all rows are serialized.
Side effects checked on both sides of the boundary: (1) the empty-playlist case still works —
`test_empty_playlist_returns_empty_list` passes, since iterating an empty list yields `[]` (the
`[:-1]` happened to also return `[]` there, so that case never exposed the bug); (2) ordering is
unchanged — `test_playlist_returns_songs_in_order` now sees all 5 tracks in position order; (3)
the seeded 7-entry playlist now returns 7. All 3 tests in `test_playlists.py` pass (previously
1/3).
