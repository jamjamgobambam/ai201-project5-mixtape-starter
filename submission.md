# Mixtape Bugfixes

## Codebase Map

### Data Models

There are 7 models: User, Playlist, Notification, Rating, ListeningEvent, Song, and Tag.

SQLAlchemy uses `db.Model` to define a table for each entity, `db.Relationship` to establish one-to-many or many-to-many relationships, and `db.Table` to set up complex many-to-many relationships — for example, a Song has many Tags and a Tag is associated with many Songs.

### Routers and Services

There are 4 routes: `feed`, `playlists`, `songs`, and `users`, each with its own service: `feed_service`, `notification_service`, `playlist_service`, `search_service`, and `streak_service`. 
`feed` - Know which friends recently listened to and their activities.
`playlists` - Create and get playlists, add songs.
`songs` - Search, listen, rate songs
`users` - Get user streak, notifications and also read them.
 Each router handles data validation and empty values, and delegates the actual business logic to its respective service.

### Data Flow

When a user creates a playlist for the first time, they hit the `POST playlist/` endpoint in `playlists.py`. This takes the `name`, `created_by`, and `is_collaborative` fields, with `name` and `created_by` required. This calls `create_playlist` from `playlist_service.py`, which looks up the user in the User table, creates a Playlist object, and inserts it into the Playlists table. Since this uses a Blueprint, it allows the routing to be defined, reused, and given a unique namespace for anything playlist-related.

---

## Bug 1: My Listening Streak Keeps Resetting

### Reproduction of Bug

When running pytest against `tests/`, `test_streak_increments_on_sunday` in `test_streaks.py` threw an error.

### How the Root Cause Was Found

I traced the issue to the `update_listening_streak` function and checked what could trigger the streak reset:

1. **Line 58:** If the `last_listened` field for the user is `None` (i.e., this is the first song they've listened to), the streak resets. I ruled this out as the issue, since this service always sets that field.
2. **Line 73:** If `days_since_last > 1` (more than one day since they last listened), or `days_since_last == 1` **and** `today.weekday() == 6` (only one day since the last listen, but today is Sunday), the streak resets. So a user would see their streak reset whenever the day they listen is a Sunday, even if it's only been one day since their last listen — or whenever more than one day has passed, regardless of the day of the week.

### Root Cause

In `update_listening_streak`, Line 73 introduces the extra condition `today.weekday() != 6`. The only valid case for a streak to reset is when more than a day has passed. This extra condition also resets the streak whenever the current day is not a Sunday, which has nothing to do with the streak logic.

### Fix and Side Effects

**Fix:** Removing `today.weekday() != 6` from the condition ensures that `days_since_last` is the only relevant check performed.

**Side Effects:** `record_listening_event` is the function that calls `update_listening_streak`. Unit testing and user testing confirmed that no functionality broke for either function.

---

## Bug 2: Friends Listening Now Shows People From Yesterday

### Reproduction of Bug

Get a user ID from the User table, then make a curl request to `GET feed/<user_id>/listening-now`:

```bash
curl -X GET http://localhost:9000/feed/178764e6-ca0f-4ab0-b3a1-693744f26b7a/listening-now
```

```json
{"count":3,"feed":[{"friend":{"id":"f633d101-ae06-4bdb-b4de-13580daad5dc","last_listened_at":"2026-06-30T23:50:40.569017","listening_streak":3,"username":"darius"},"listened_at":"2026-07-01T23:40:40.569017","song":{"album":null,"artist":"The Wanderers","genre":"indie rock","id":"3ae88dfb-ac1b-4d7c-bfec-fef14ecccf55","share_note":null,"shared_at":"2026-06-26T23:50:40.569017","shared_by":"178764e6-ca0f-4ab0-b3a1-693744f26b7a","tags":[],"title":"Midnight Drive"}},{"friend":{"id":"1a0deefd-7047-4599-b67b-bf8909737576","last_listened_at":null,"listening_streak":0,"username":"simone"},"listened_at":"2026-07-01T23:35:40.569017","song":{"album":null,"artist":"Elara Moon","genre":"ambient","id":"a9db71fe-f6ab-4554-9b13-f6dcdc3b4c52","share_note":null,"shared_at":"2026-06-26T23:50:40.569017","shared_by":"178764e6-ca0f-4ab0-b3a1-693744f26b7a","tags":[],"title":"Still Waters"}},{"friend":{"id":"33a0f114-2df8-4e20-af16-4cedba960551","last_listened_at":"2026-07-01T20:50:40.569017","listening_streak":12,"username":"kenji"},"listened_at":"2026-07-01T23:30:40.569017","song":{"album":null,"artist":"Coastal Highway","genre":"indie","id":"3af684aa-cb33-4954-b0dc-a49a7b08d1eb","share_note":null,"shared_at":"2026-06-26T23:50:40.569017","shared_by":"178764e6-ca0f-4ab0-b3a1-693744f26b7a","tags":[],"title":"First Light"}}]}
```

Based on the response, the `listened_at` values are:

- `2026-07-01T23:40:40.569017`
- `2026-07-01T23:35:40.569017`
- `2026-07-01T23:30:40.569017`

Based on Lines 112–117 in `seed_data.py`, recently listened events should fall within a 30-minute threshold. But based on the response above, the endpoint is pulling every record beyond that threshold.

### How the Root Cause Was Found

From the same route used in reproduction, I traced the call from `listening-now` to `get_friends_listening_now` in `feed_service.py`.

### Root Cause

- **Line 32** calculates the cutoff for valid dates: `cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD`
- **Line 13** defines `RECENT_THRESHOLD = timedelta(hours=24)`
- **Line 45** filters using `ListeningEvent.listened_at >= cutoff`

Together, this meant `listened_at` timestamps could be up to 24 hours behind the present time and still be included — which didn't match the expectations set by `seed_data.py`.

### Fix and Side Effects

**Fix:** Line 13 was changed to:

```python
RECENT_THRESHOLD = timedelta(minutes=30)
```

After making the change, I retested the reproduction scenario:

**Before 7:00 PM**

```bash
curl -X GET http://localhost:9000/feed/178764e6-ca0f-4ab0-b3a1-693744f26b7a/listening-now
```

```json
{"count":3,"feed":[{"friend":{"id":"f633d101-ae06-4bdb-b4de-13580daad5dc","last_listened_at":"2026-06-30T23:50:40.569017","listening_streak":3,"username":"darius"},"listened_at":"2026-07-01T23:40:40.569017","song":{"album":null,"artist":"The Wanderers","genre":"indie rock","id":"3ae88dfb-ac1b-4d7c-bfec-fef14ecccf55","share_note":null,"shared_at":"2026-06-26T23:50:40.569017","shared_by":"178764e6-ca0f-4ab0-b3a1-693744f26b7a","tags":[],"title":"Midnight Drive"}},{"friend":{"id":"1a0deefd-7047-4599-b67b-bf8909737576","last_listened_at":null,"listening_streak":0,"username":"simone"},"listened_at":"2026-07-01T23:35:40.569017","song":{"album":null,"artist":"Elara Moon","genre":"ambient","id":"a9db71fe-f6ab-4554-9b13-f6dcdc3b4c52","share_note":null,"shared_at":"2026-06-26T23:50:40.569017","shared_by":"178764e6-ca0f-4ab0-b3a1-693744f26b7a","tags":[],"title":"Still Waters"}},{"friend":{"id":"33a0f114-2df8-4e20-af16-4cedba960551","last_listened_at":"2026-07-01T20:50:40.569017","listening_streak":12,"username":"kenji"},"listened_at":"2026-07-01T23:30:40.569017","song":{"album":null,"artist":"Coastal Highway","genre":"indie","id":"3af684aa-cb33-4954-b0dc-a49a7b08d1eb","share_note":null,"shared_at":"2026-06-26T23:50:40.569017","shared_by":"178764e6-ca0f-4ab0-b3a1-693744f26b7a","tags":[],"title":"First Light"}}]}
```

**At 7:06 PM**

```bash
curl -X GET http://localhost:9000/feed/178764e6-ca0f-4ab0-b3a1-693744f26b7a/listening-now
```

```json
{"count":1,"feed":[{"friend":{"id":"f633d101-ae06-4bdb-b4de-13580daad5dc","last_listened_at":"2026-06-30T23:50:40.569017","listening_streak":3,"username":"darius"},"listened_at":"2026-07-01T23:40:40.569017","song":{"album":null,"artist":"The Wanderers","genre":"indie rock","id":"3ae88dfb-ac1b-4d7c-bfec-fef14ecccf55","share_note":null,"shared_at":"2026-06-26T23:50:40.569017","shared_by":"178764e6-ca0f-4ab0-b3a1-693744f26b7a","tags":[],"title":"Midnight Drive"}}]}
```

**At 7:17 PM**

```bash
curl -X GET http://localhost:9000/feed/178764e6-ca0f-4ab0-b3a1-693744f26b7a/listening-now
```

```json
{"count":0,"feed":[]}
```

**Explanation for why the results changed correctly:**

The three events and their fixed timestamps:

| Friend | `listened_at` | Falls out of the 30-min window once "now" passes |
|---|---|---|
| kenji | 23:30:40 | 24:00:40 |
| simone | 23:35:40 | 24:05:40 |
| darius | 23:40:40 | 24:10:40 |

- **First curl (count: 3):** all three fell within the window. Server "now" was still ≤ 24:00:40, so `now − 30min ≤ 23:30:40`, keeping kenji, simone, and darius all inside the window.
- **Second curl (count: 1):** by the time it re-ran, server "now" had passed 24:00:40 and 24:05:40, pushing the cutoff past kenji's and simone's timestamps (`now − 30min > 23:30:40` and `> 23:35:40`), so they dropped out. Darius's 23:40:40 was still `≥ now − 30min`, so he's the only one left.
- **Validity going forward:** darius will also disappear once real time passes 24:10:40 (i.e., 23:40:40 + 30min). After that, this same seeded data will return `count: 0` for this user.

#### Regression Tests

Since live testing against real time isn't always feasible, I also added tests simulating these scenarios under `tests/test_feed.py`. The following tests specifically validates for the events following the threshold of recent 30 minutes:
`test_recent_event_is_included`: Checks for the relevant events to be included within the time window.
`test_stale_event_is_excluded`: Checks for whether the list of event updates when the time window for has passed.
Running these tests would have caught the bug early on.

#### Side Effects

Regression and user testing confirmed that no functionality broke. `get_friends_listening_now` is only used in `feed.py`, so this change does not affect other services.

---

## Bug 3: The Same Song Keeps Showing Up Twice in Search

### Reproduction of Bug

I first looked at `search_songs()` in `search_service.py` and saw that it used the `song_tags` table to get the list of tags, and hypothesized that this could be the source of the issue.

I then searched for songs with more than one tag:

```sql
SELECT song.id, song.title, GROUP_CONCAT(tag.name, ', ') AS tags
FROM song
LEFT JOIN song_tags ON song.id = song_tags.song_id
LEFT JOIN tag ON tag.id = song_tags.tag_id
GROUP BY song.id, song.title;
```

I chose "Crown Heights Anthem" as the test case, since it had 3 tags: `["rap", "hip-hop", "boom bap"]`.

I then hit the search endpoint using the song name:

```bash
curl -G "http://localhost:9000/songs/search" --data-urlencode "q=Crown Heights"
```

Surprisingly, it returned only one result:

```json
{"count":1,"results":[{"album":null,"artist":"Borough Kings","genre":"rap","id":"48508db6-8b2c-4a82-b064-687df84a075a","share_note":null,"shared_at":"2026-06-30T20:06:15.807978","shared_by":"f597475e-3afb-42e6-8740-30df30635a5d","tags":["rap","hip-hop","boom bap"],"title":"Crown Heights Anthem"}]}
```

### How the Root Cause Was Found

Using AI and further research, I found the following explanation: `session.query(Song)...all()` (the legacy `Query` API) generates the same SQL as the 2.0-style `select()`, but adds an extra post-processing step that auto-dedupes full-entity results by primary key.

This explained why, even though the join with `song_tags` happened as expected, the Song results were automatically deduplicated by primary key.

Here's a query and response that produces duplicate song results (one per tag), for comparison:

```python
# stmt = (
#     db.session.query(Song)
#     .outerjoin(song_tags, Song.id == song_tags.c.song_id)
#     .filter(
#         db.or_(
#             Song.title.ilike(f"%{query}%"),
#             Song.artist.ilike(f"%{query}%"),
#         )
#     )
# )
#
# results = db.session.execute(stmt.statement).scalars().all()
```

```json
{"count":3,"results":[{"album":null,"artist":"Borough Kings","genre":"rap","id":"48508db6-8b2c-4a82-b064-687df84a075a","share_note":null,"shared_at":"2026-06-30T20:06:15.807978","shared_by":"f597475e-3afb-42e6-8740-30df30635a5d","tags":["rap","hip-hop","boom bap"],"title":"Crown Heights Anthem"},{"album":null,"artist":"Borough Kings","genre":"rap","id":"48508db6-8b2c-4a82-b064-687df84a075a","share_note":null,"shared_at":"2026-06-30T20:06:15.807978","shared_by":"f597475e-3afb-42e6-8740-30df30635a5d","tags":["rap","hip-hop","boom bap"],"title":"Crown Heights Anthem"},{"album":null,"artist":"Borough Kings","genre":"rap","id":"48508db6-8b2c-4a82-b064-687df84a075a","share_note":null,"shared_at":"2026-06-30T20:06:15.807978","shared_by":"f597475e-3afb-42e6-8740-30df30635a5d","tags":["rap","hip-hop","boom bap"],"title":"Crown Heights Anthem"}]}
```

Note that there are multiple ways to remove the deduplication behavior, but it only applies when querying full entities.

### Root cause

The query can fail if the query gets ported to the SQLAlchemy>=2.0.x newer `select() + execute()` and when it does, the root cause of duplication is `outerjoin()`. Under the hood, it returns multiple songs for each tag. 

### Fix and Side Effects

Adding a TODO and note about this matter for any future engineer who ports to the newer query format is the helpful for understanding what can fail. 

However, `outer_join` is not actually needed here: the query does not use any attributes from `song_tags` as the Song model lazy loads its Tags directly from `song_tags`. Removing 
    ``` python
            .outerjoin(song_tags, Song.id == song_tags.c.song_id)
    ```
from the query removes the problematic code without affecting the results.

Specfically, the test `test_search_no_duplicates_single_tag_song` in `test_search.py` passes.

This is a classic case of library behavior affecting the outcome of a piece of code that, on its own works correctly, but its underlying behavior could produce a different result that no test could have caught in advance.

---

## Bug 4: I Got Notified When a Friend Added My Song to a Playlist, but Not When They Rated It

### Reproduction of Bug

The seed data has a relevant example at Line 171, which was used to obtain the following data:

1. Song
2. Song sharer
3. Song listener/rater ID

**Step 1:** Get the notifications for the song sharer:

```bash
curl -X GET "http://localhost:9000/users/178764e6-ca0f-4ab0-b3a1-693744f26b7a/notifications?unread_only=false"
```

```json
{"count":1,"notifications":[{"body":"darius added your song 'Midnight Drive' to the playlist 'Late Night Vibes'.","created_at":"2026-07-01T23:50:40.594485","id":"1d3a183b-0aa1-4148-9173-046f304be6fe","read":false,"type":"song_added_to_playlist","user_id":"178764e6-ca0f-4ab0-b3a1-693744f26b7a"}]}
```

**Step 2:** Rate the song as the song listener:

```bash
curl -X POST http://localhost:9000/songs/3ae88dfb-ac1b-4d7c-bfec-fef14ecccf55/rate \
  -H "Content-Type: application/json" \
  -d '{"user_id": "f633d101-ae06-4bdb-b4de-13580daad5dc", "score": 3}'
```

```json
{"id":"30583878-ec62-43b6-a755-24a54c334bfc","rated_at":"2026-07-02T00:35:13.345241","score":3,"song_id":"3ae88dfb-ac1b-4d7c-bfec-fef14ecccf55","user_id":"f633d101-ae06-4bdb-b4de-13580daad5dc"}
```

**Step 3:** Get the notifications for the song sharer again:

```bash
curl -X GET "http://localhost:9000/users/178764e6-ca0f-4ab0-b3a1-693744f26b7a/notifications?unread_only=false"
```

```json
{"count":1,"notifications":[{"body":"darius added your song 'Midnight Drive' to the playlist 'Late Night Vibes'.","created_at":"2026-07-01T23:50:40.594485","id":"1d3a183b-0aa1-4148-9173-046f304be6fe","read":false,"type":"song_added_to_playlist","user_id":"178764e6-ca0f-4ab0-b3a1-693744f26b7a"}]}
```

This confirms the reported issue: the rating notification was never received.

### How the Root Cause Was Found

I traced the call from `add_to_playlist` in `notification_service.py`, based on the seeded data and reproduction steps. Lines 65–70 show how the notification is sent to the song sharer when a song is added to a playlist. The same file also contains `rate_song`, which is where the rating is received and stored.

### Root Cause

`rate_song` had no notification logic, even though it lives in `notification_service`. It stored the rating correctly but never notified the song sharer.

### Fix and Side Effects

**Fix:** The following code was added after Line 108 (`db.session.commit()`):

```python
if song.shared_by != user_id:
    create_notification(
        user_id=song.shared_by,
        notification_type="song_rated_by_user",
        body=f"{rater.username} rated your song '{song.title}' as '{rating.score}'.",
    )
```

The notification type, username, and score are included in the notification body.

After the change, I re-ran the reproduction steps:

```bash
curl -X GET "http://localhost:9000/users/178764e6-ca0f-4ab0-b3a1-693744f26b7a/notifications?unread_only=false"
```

```json
{"count":2,"notifications":[{"body":"darius rated your song 'Midnight Drive' as '3'.","created_at":"2026-07-02T00:42:01.202869","id":"e70fa4c7-9e46-4eba-9e34-3c6a85af1241","read":false,"type":"song_rated_by_user","user_id":"178764e6-ca0f-4ab0-b3a1-693744f26b7a"},{"body":"darius added your song 'Midnight Drive' to the playlist 'Late Night Vibes'.","created_at":"2026-07-01T23:50:40.594485","id":"1d3a183b-0aa1-4148-9173-046f304be6fe","read":false,"type":"song_added_to_playlist","user_id":"178764e6-ca0f-4ab0-b3a1-693744f26b7a"}]}
```

Compared to before, the song sharer now receives a notification after another user rates their song.

**Side Effects:** This change only affects `songs.py`, so unit testing and user testing confirmed that no other functionality broke.

---

## Bug 5: The Last Song in a Playlist Never Shows Up

### Reproduction of Bug

Get a random playlist ID from `mixtape.db` via a SQL query (AI can assist in constructing this):

```sql
SELECT * FROM Playlist;
```

`167a25c9-a048-45b2-a951-f4e00aab91b3` — "Late Night Vibes"

Use this playlist ID to make a `GET playlists/<playlist_id>/songs` request:

```json
{"count":6,"songs":[{"album":null,"artist":"The Wanderers","genre":"indie rock","id":"3f3c69c1-80c2-4958-99e6-c1951cadccb5","share_note":null,"shared_at":"2026-06-26T16:28:30.530247","shared_by":"94b0aca3-8e41-4630-a1c0-e92a8f25684d","tags":[],"title":"Midnight Drive"},{"album":null,"artist":"Elara Moon","genre":"ambient","id":"6bf8b3db-e2cc-439c-8253-49c6792e0ac4","share_note":null,"shared_at":"2026-06-26T16:28:30.530247","shared_by":"94b0aca3-8e41-4630-a1c0-e92a8f25684d","tags":[],"title":"Still Waters"},{"album":null,"artist":"Coastal Highway","genre":"indie","id":"2aaf3380-8618-45dd-ab1e-58ad51f8670e","share_note":null,"shared_at":"2026-06-26T16:28:30.530247","shared_by":"94b0aca3-8e41-4630-a1c0-e92a8f25684d","tags":[],"title":"First Light"},{"album":null,"artist":"Street Collective","genre":"hip-hop","id":"4f45aaf5-bce8-43c0-b40b-08dfda663b24","share_note":null,"shared_at":"2026-06-28T16:28:30.530247","shared_by":"a62adbea-dc84-49fe-b5c1-08e3d164f73e","tags":["hip-hop"],"title":"Block Party"},{"album":null,"artist":"Nova Blix","genre":"lo-fi","id":"9c7f13b1-a9ed-46e0-973b-124618676227","share_note":null,"shared_at":"2026-06-28T16:28:30.530247","shared_by":"a62adbea-dc84-49fe-b5c1-08e3d164f73e","tags":["lo-fi"],"title":"Late Night Session"},{"album":null,"artist":"Solange K","genre":"r&b","id":"643c31bd-6fb7-4ff8-912b-1fed011b02b1","share_note":null,"shared_at":"2026-06-28T16:28:30.530247","shared_by":"a62adbea-dc84-49fe-b5c1-08e3d164f73e","tags":["r&b"],"title":"Golden Hour"}]}
```

Since the reported bug is that the last song doesn't show up, I verified whether the playlist in the database actually has the same number of songs, using a query joining on `playlist_entries` by playlist ID (AI-assisted, since I wasn't familiar with the Flask shell):

```sql
SELECT song.*
FROM song
JOIN playlist_entries ON song.id = playlist_entries.song_id
WHERE playlist_entries.playlist_id = '167a25c9-a048-45b2-a951-f4e00aab91b3';
```

```
2aaf3380-8618-45dd-ab1e-58ad51f8670e|First Light|Coastal Highway||indie|94b0aca3-8e41-4630-a1c0-e92a8f25684d|2026-06-26 16:28:30.530247|
3f3c69c1-80c2-4958-99e6-c1951cadccb5|Midnight Drive|The Wanderers||indie rock|94b0aca3-8e41-4630-a1c0-e92a8f25684d|2026-06-26 16:28:30.530247|
4f45aaf5-bce8-43c0-b40b-08dfda663b24|Block Party|Street Collective||hip-hop|a62adbea-dc84-49fe-b5c1-08e3d164f73e|2026-06-28 16:28:30.530247|
643c31bd-6fb7-4ff8-912b-1fed011b02b1|Golden Hour|Solange K||r&b|a62adbea-dc84-49fe-b5c1-08e3d164f73e|2026-06-28 16:28:30.530247|
6bf8b3db-e2cc-439c-8253-49c6792e0ac4|Still Waters|Elara Moon||ambient|94b0aca3-8e41-4630-a1c0-e92a8f25684d|2026-06-26 16:28:30.530247|
7c34d46d-c356-4cea-b628-4e5b3d419d37|Free Throws|Hoop Dreams||rap|a62adbea-dc84-49fe-b5c1-08e3d164f73e|2026-06-28 16:28:30.530247|
9c7f13b1-a9ed-46e0-973b-124618676227|Late Night Session|Nova Blix||lo-fi|a62adbea-dc84-49fe-b5c1-08e3d164f73e|2026-06-28 16:28:30.530247|
```

(The size of the result alone would confirm this, but the full query is included for reference.)

This shows "Late Night Vibes" actually has 7 songs, but the endpoint only returned 6.

### How the Root Cause Was Found

I traced the request from reproduction to `get_playlist_songs` in `playlist_service.py`. The filtering logic looked correct until Line 66.

### Root Cause

In `playlist_service.py`, `get_playlist_songs` filters songs correctly, but Line 66 has an incorrect loop: `for songs in songs[:-1]` iterates over all songs except the last one.

This was also flagged by two failing tests in `test_playlists.py` — `test_playlist_returns_all_songs` and `test_playlist_returns_songs_in_order` — before the fix:

```
FAILED tests/test_playlists.py::test_playlist_returns_all_songs - AssertionError: assert 4 == 5
FAILED tests/test_playlists.py::test_playlist_returns_songs_in_order - AssertionError: assert ['Track 1', '...3', 'Track 4'] == ['Track 1', '...4', 'Track 5']
```

### Fix and Side Effects

**Fix:** Changing Line 66 to `for songs in songs` resolved the issue. The tests above now pass.

**Side Effects:** `get_playlist_songs` is only used once, in `playlists.py`, so the fix was verified both by re-running the original request (confirming all 7 items are returned) and by the passing unit tests.

---

## AI Tool Plan

- Used Claude Code to explain the data models, and to generate curl requests and SQL queries as part of reproducing bugs.
- Used Claude Code to research the failed reproduction attempt for **Bug 3**, and to document how it can be reproduced with a different query structure. Claude Code initially suggested a fix; after being told the code worked as intended, it corrected itself and explained the underlying SQLAlchemy legacy `Query()` vs. `select()` mechanics. I confirmed this independently via [this reference](https://dokk.org/documentation/sqlalchemy/rel_1_4_50/orm/session_basics/#querying-1-x-style).

## Commit Log for `bugfix/mixtape`

```
1aaf760 (HEAD -> bug3fix, origin/bug3fix) fix:  searching for a song provided duplicated results; removed uneeded outerjoin
0b8a26c (origin/main, origin/HEAD, main) Fix documentation on regression tests for Bug 2
0d1d81c no-op: Update commit log in submission.md
1407735 no-op: Modify submission.md to be consistent and readable
aba20c3 fix: listening streak kept getting reset; removed weekday check to prevent reset on Sundays
4bad6d5 fix: listening_now() showed friends listening until yesterday from current time; corrected RECENT_THRESHOLD from 24 hours to 30 min to get recent listens upto 30 min
342a7d4 fix: user did not get notification for another user's rating on their song; added notification to rate_song
486f823 fix: searching for a song provided duplicated results; current code works as intended; documented query behavior that failed reproduction
0128cf3 fix: get_playlist_songs() does not return the last song; changed songs[:-1] to songs
2dfdeaa Add .gitignore file and update README with setup instructions
7b64551 initial commit
```
