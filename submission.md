Mixtape
A social music app where friends share songs, build collaborative playlists, and track listening stats.

This is the starter repo for Project 5: Mixtape Bug Hunt. The app has five open issues in its tracker. Your job is to find, fix, and document at least three of them.

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

## AI Usage - Summarize Service Files (see Service Summaries section above)
1. As directed by the project instructions, I gave AI the contents of a service file to summarize what is this module responsible for? and What are its main functions and wht does each one do? 

**Full disclosure:** In doing this, the AI tool identified two bugs it identified: the first in playlist_service.py": 

"Bug spotted: In get_playlist_songs() on playlist_service.py:63:. The docstring says "returns all songs in the playlist," but songs[:-1] drops the final song. It should be songs (no slice)."

The second bug it identified was in streak_service.py.

"Bug spotted: In update_listening_streak() on streak_service.py:67: elif days_since_last == 1 and today.weekday() != 6: The today.weekday() != 6 condition skips the streak increment on Sundays (weekday 6), which means listening on a Sunday after Saturday never extends the streak. This looks unintentional — the streak rules in the docstring make no mention of Sunday being excluded."

In both cases, it asked if it wanted me to fix the bug, but I delcined in order to follow the project instructions. 

## AI Usage - Test Coverage

I asked AI to validate that all three test files (test_playlists.py, test_search.py, and test_streaks.py) were correct and complete. Doing this allowed the AI to detect more bugs, as described below. I also directed AI to write tests for the files that were missing coverage, and to write test files for the services that didn't have any tests at all. 

### test_playlists.py — Correct, but incomplete coverage
The 3 tests are well-structured. test_playlist_returns_all_songs correctly expects 5 songs and will fail due to the songs[:-1] bug identified earlier. 

**Missing coverage:** 
    1. get_playlist_songs with an invalid playlist_id (should raise ValueError)
    2. create_playlist is imported but never tested

### test_search.py — Has a bug in the service, tests are correct
The 5 tests are well-written and will correctly catch the duplicate-results bug in search_service.py. This identified another bug (the duplicate results bug in search_service.py, which had not been identified before.). 

The issue: search_songs uses .outerjoin(song_tags, ...) without a .distinct(), so songs with multiple tags appear multiple times in results. test_search_no_duplicates_multi_tag_song will fail until that's fixed. 

Missing coverage:
    - Case-insensitive matching (e.g. query "borough" should match "Borough Kings")
    - get_song is not tested at all (not even imported)


### test_streaks.py
For test_streaks.py, it said all 5 bugs are are well-written and cover the key cases: new user, consecutive days, same-day double count, skipped day, and the Sunday edge case. Notably, test_streak_increments_on_sunday directly tests the bug flagged in streak_service.py (the weekday() != 6 condition) — so this test will fail until that bug is fixed.

## AI Usage - Reseed Data
I had to use AI to reseed the data in seed_data.py, because the data was stale and I was not able to reproducethe error. 


## Codebase Orientation/ Code Mapping -> Data Flow

### Feed Routes

1. feed.py, with route: GET/feed/user_id/listening-now        -->  feed_service.get_friends_listening_now(user_id) 
2. feed.py, with route: GET/feed/user_id/activity             -->  feed_service.get_activity_feed(user_id)   

### Playlists 

1. playists.py, with route: POST/playists                    -->  playlist_service.create_playlist(name, created_by, is_collaborative)
2. playists.py, with route: GET/playists//playlist_id        -->  playlist_service.get_detail(playlist_id):
3. playists.py, with route: GET/playists//playlist_id>/songs -->  playlist_service.get_playlist_songs(playlist_id)
4. playists.py, with route: POST/playists/playlist_id/songs  -->  playlist_service.dd_to_playlist(playlist_id, song_id, added_by)


### Songs

1. songs.py, with route:    GET/songs/search                 --> search_service.search_songs(query: str)
2. songs.py, with route:    GET/songs/song_id                --> search_service.get_song(song_id)
3. songs.py, with route:    POST/songs/song_id/rate          --> notification_service.rate_song(user_id: str, song_id: str, score: int)
4. songs.py, with route:    POST/songs/song_id/listen        --> streak_service.record_listening_event(user_id:, song_id)

### Users
1. users.py, with route:    GET/users/user_id                --> will call db.session.get(User, user_id), and return jsonify({"error": "User not found"}) or jsonify(user.to_dict())
2. users.py, with route:    GET/users/user_id/streak         --> streak_service.get_streak(user_id)
3. users.py, with route:    GET/users/user_id/notifications --> notification_service.get_notifications(user_id)
4. users.py, with route:    POST/users/notifications/notification_id/read  --> notification_service.read_notification(notification_id) and try notification_service.mark_as_read(notification_id)

## Codebase Orientation / Code Mapping  -> Service Summaries (provided by AI, as describedin AI Usage section below)

### feed_service.py

This module is the feed-aggregation service for social listening activity.

1. It is responsible for: Building a “friends listening now” feed via get_friends_listening_now(...) in feed_service.py:14:
    A. Building a “friends listening now” feed via get_friends_listening_now(...) in feed_service.py:14:
    B. Validates the requesting user exists.
    C. Looks at only that user’s friends.
    D. Filters events to a recent window (24 hours via RECENT_THRESHOLD).
    E. Sorts by newest first.
    F. Deduplicates so each friend appears at most once (their latest event only).
    G. Returns normalized dicts with friend, song, and listened_at.

2. Building a broader activity stream via get_activity_feed(...) in feed_service.py:62:
    A. Validates user exists.
    B. Pulls friends’ listening events (no recency cutoff).
    C. Sorts newest first and applies a configurable limit (default 20).
    D. Returns event-by-event dicts with friend, song, and listened_at.

In short: it’s the read-side service that queries listening events and shapes them into API-ready social feed payloads.

### notification_service.py

This module is mainly responsible for managing user notifications and the specific social interactions that trigger them.

1. Core Notification CRUD:
    A. create_notification(): Generates a new notification for a user.
    B get_notifications(): Fetches a user's notifications, with an option to filter for unread only.
    C. mark_as_read(): Updates a specific notification's status to read.
2. Social Interaction Workflows (The Triggers):
    A. add_to_playlist(): Adds a song to a playlist and automatically notifies the user who originally shared the song ("User X added your song 'Y' to playlist 'Z'").
    B. rate_song(): Saves or updates a user's 1-5 score for a particular song.
    C. Essentially, it acts as the business logic layer for recording interactions between friends and alerting users when those happened (where applicable) alerting them about those interactions.

### playlist_service.py

This module handles playlist creation and retrieval. Its four functions:

1. Core Notification CRUD:
    A. create_playlist() — Validates the user exists, then creates and persists a new Playlist (with an optional is_collaborative flag).
    B. get_playlist_songs() — Fetches a playlist's songs ordered by their position in the playlist_entries join table.
    C. get_playlist() — Returns just a playlist's metadata (no songs).
    D. get_user_playlists() — Returns all playlists created by a given user.

### search_service.py

This module is responsible for song lookup. It has two functions:

1. Core Notification CRUD:
    A. search_songs(query) — Searches songs by title or artist using a case-insensitive LIKE match (%query%). It outer-joins the song_tags table so tag data is available, and returns a list of song dicts.
    B. get_song(song_id) — Fetches a single song by its UUID, raising a ValueError if not found.

That's its entire scope — no writes, no side effects, just read-only song retrieval.

### streak_service.py

This module handles daily listening streak tracking. It has three functions:

1. Core Notification CRUD:
    A. record_listening_event() — Creates a ListeningEvent record for a user/song pair, then calls update_listening_streak to update the user's streak before committing both changes together.
    B. update_listening_streak() — Applies the streak rules based on days_since_last listened:
        - First time ever → streak = 1
        - Already listened today → no change
        - Listened yesterday → streak + 1 (with a caveat — see below)
        - Gap of 2+ days → streak resets to 1
    C. get_streak() — Simple read returning the user's current listening_streak integer.

### models.py

models.py defines the entire database schema — every SQLAlchemy model and association table used across the app. Here's the breakdown:

Association Tables (join tables with no model class of their own):

    A.friendships — many-to-many self-referential User↔User relationships
    B. song_tags — many-to-many Song↔Tag relationships
    C. playlist_entries — many-to-many Playlist↔Song with extra columns (position, added_by, added_at)


Model Classes (each has a to_dict() method that serializes it for API responses):

| Model	            | Key fields	                                        | Relationships
| User	            |username, email, listening_streak, last_listened_at	| friends (self-ref), shared songs, ratings, listening events, notifications, playlists
| Tag	            | name	                                                | (no to_dict)
| Song	            | title, artist, album, genre, shared_by, share_note	| ratings, listening events, tags
| ListeningEvent	| user_id, song_id, listened_at	                        | —
| Rating	        | user_id, song_id, score (1–5)	                        | unique constraint per user+song pair
| Playlist	        | name, created_by, is_collaborative	                | songs (via playlist_entries)
| Notification	    | user_id, notification_type, body, read	            | —

All primary keys are UUID strings generated by the generate_uuid() helper at the top of the file.


## Bug Fixes

| # |------------------------Title------------------------------------------| Affected service
| 1	| My listening streak keeps resetting	                                | streak_service.py
| 2	| Friends Listening Now shows people from yesterday	                    | feed_service.py
| 3	| The same song keeps showing up twice in search	                    | search_service.py
| 4	| I got notified when a friend added my song to a playlist but not when they rated it	  | notification_service.py
| 5	| The last song in a playlist never shows up	                        | playlist_service.py

## Bug Fixes: Notes from AI, Assignment, and TODOs

<!-- Notes from Assignment: 

For Issue #3 (duplicates), the bug is conditional — think about what conditions trigger the second code path that produces the duplicate.

For Issue #4 (notifications), the root cause is architectural, not a typo. Look at the pattern used for the working notification and compare it line-by-line to the missing one.-->


<!-- Notes from AI 

<!-- This identified another bug (the duplicate results bug in search_service.py, which had not been identified before.). The issue: search_songs uses .outerjoin(song_tags, ...) without a .distinct(), so songs with multiple tags appear multiple times in results. test_search_no_duplicates_multi_tag_song will fail until that's fixed. (#3)>

<!--TODO: Bug spotted: In update_listening_streak() on streak_service.py:67: elif days_since_last == 1 and today.weekday() != 6: The today.weekday() != 6 condition skips the streak increment on Sundays (weekday 6), which means listening on a Sunday after Saturday never extends the streak. This looks unintentional — the streak rules in the docstring make no mention of Sunday being excluded. (#1)-->

<!-- TODO: Bug spotted: In get_playlist_songs() on playlist_service.py:63:. The docstring says "returns all songs in the playlist," but songs[:-1] drops the final song. It should be songs (no slice). (#5)-->

Root Cause Analysis Format
For each of the 3+ bugs you fix, write an entry in your submission doc with all five of these fields:

## Root Cause Analysis Formatting

### Issue number and title

***How you reproduced it*** — What steps did you take to confirm the bug exists before touching any code? What inputs, sequence of actions, or data condition triggered the behavior?
***How you found the root cause*** — Which files did you look at? What was your navigation path? What moment made you confident you'd found the right place — not just a suspicious area, but the specific cause?
***The root cause*** — In plain English, explain exactly what was wrong. Not "there was a bug in the streak logic" — explain the specific condition, comparison, or missing step that caused the problem.
***Your fix and side-effect check*** — What did you change and why does that change fix the root cause? What related functionality did you check afterward to confirm you didn't break anything?

What a precise root cause looks like vs. a surface-level one:

❌ Surface-level: "The streak reset logic had a bug where it wasn't handling Sundays correctly."

✅ Precise: "Python's datetime.weekday() returns 6 for Sunday, but the streak code was checking weekday() == 0 to detect the start of a new week, which matches Monday instead. Any streak update on a Sunday was treated as a mid-week entry, so the streak never reset when the week turned over on Sunday nights. The fix was to change the comparison to isoweekday() == 7 (Sunday = 7 in ISO convention), which correctly identifies the week boundary."

### Explanations 
At least 2 explanations name a specific function or variable and explain the mechanism: why that specific thing caused the reported behavior under the specific conditions it manifested (e.g., "only on Sundays," "only for songs with multiple tags").

At least one explanation demonstrates causal reasoning — it explains not just what was wrong but why the correct behavior requires something different.

### Navigation Strategy
- At least 3 entries describe a real navigation path: which files were looked at, what was followed (a function call, a query, a data flow), and what moment made the student confident they'd found the root cause.
- The strategies described reflect deliberate exploration, not a lucky first guess. The entries show the student tracing a path, not just arriving at an answer.

### Side-Effect Checks
- At least 3 entries describe a specific, deliberate check — what related functionality was looked at after the fix to confirm it wasn't affected, and why that check was sufficient.
- At least one entry describes a check that goes beyond "the app still ran" — it identifies a specific behavior or code path that could plausibly have been affected by the fix and confirms it wasn't.

### Test Results Before Beginning Bug Fixes
![alt text](<Images/Test_Files/1. Test Run 1.png>)

## 1. Root Cause Analysis for Bug Fix 5: The last song in a playlist never shows up

***Navigaation Strategy***
This bug is a problem with this ruote: it is not retrieving the last song in a playlist given a playlist id.

Route: playists.py, with route: GET/playists//playlist_id>/songs -->  playlist_service.get_playlist_songs(playlist_id)

***Reproducting the Error***
I ran the app with the /playists//playlist_id>/songs path -> http://127.0.0.1:5000/playlists/154122e3-a8a3-420c-8baa-4e59e23c1bc7/songs

This gave back the following data:
![alt text](<Images/Bug_Verifications_Before_Fixes/1. Bug verification before fix.png>)

In models.db, there are seven songs listed for this playlist, so I know that it is missing a song, and I verified that the song that was missing was the last songin the playlist by comparing it to the songs table. The last song is Free Throw by Hoop Dreams, and it is not being listed before the bug fix. 

***Explanation***
Following the route, I opened up the playlist_service.py file and found the function in question -> 
playlist_service.get_playlist_songs(playlist_id). 

On Line 66, the function returns: return [song.to_dict() for song in songs[:-1]]. songs[:-1] (slice) drops the final song.

***Fix***

Change return [song.to_dict() for song in songs]

***Verification After Fix***

![alt text](<Images/Bug_Verification_After_Fixes/1. Bug verification after fix - (5).png>)

***Side Effect Checks***

I didn't think that this change would impact other routes, but decided to verify that the following route call still worked as expected. 

playists.py, with route: GET/playists//playlist_id        -->  playlist_service.get_detail(playlist_id):

![alt text](<Images/Side_Effect_Checks/1. Side Effect Check After Bug Fix 5.png>)

The fix had no negative side effects, but it did produce one positive unexpected side effect:

get_playlist() (metadata-only route) — unaffected. This function returns playlist name, id, and is_collaborative only. It never calls get_playlist_songs(), so the slice change had zero impact on it. I verified this manually by calling GET /playlists/<playlist_id> and confirming it still returned correct metadata.

Positive side effect — test_playlist_returns_songs_in_order also started passing. That test expects all 5 tracks in order (Track 1 through Track 5). With songs[:-1], Track 5 was missing, causing it to fail. Removing the slice fixed both tests simultaneously, which is why "the code change fixed two of the failed tests" even though you only targeted one.

No other routes or services were affected — create_playlist() and get_user_playlists() don't call get_playlist_songs() at all.

![alt text](<Images/Test_Files/2. Test Run 2 (After Bug Fix 5).png>)

## 2. Root Cause Analysis for Bug Fix 2: Friends Listening Now shows people from yesterday	 

This bug is a problem with this route: it is showing people who listened to a playlist yesterday, not people listening now. 

***Navigaation Strategy***

This bug is a problem with this route:
feed.py, with route: GET/feed/user_id/listening-now        -->  feed_service.get_friends_listening_now(user_id)  

***Reproducting the Error***

I ran the app with the /feed/user_id/listening-now path -> http://127.0.0.1:5000/feed/4beadfa5-04db-46fe-99be-ea35a7f17a39/listening-now

This gave back the following data:
![alt text](<Images/Bug_Verifications_Before_Fixes/2. Bug verification before fix (2).png>)

The third entry, for Simone, should not be there. She was listening yesterday, which falls outside of the adjusted RECENT_THRESHOLD = timedelta(hours=1) in feed_service.py. 

***Explanation***

There are two issues here. 
1. RECENT_THRESHOLD = timedelta(hours=24) — 24 hours is too wide for "listening now." It includes anyone who listened yesterday.
2. Timezone mismatch — listened_at is stored as a naive datetime, but datetime.now(timezone.utc) produces a timezone-aware cutoff, which can cause inconsistent comparisons in SQLite.

***Fix(es)***
Two changes made to feed_service.py:

1. timedelta(hours=24) → timedelta(hours=1) — The root cause. 24 hours includes events from yesterday. 1 hour matches what "listening now" actually means.
2. datetime.now(timezone.utc) → datetime.now() — SQLAlchemy's db.Column(db.DateTime) stores naive datetimes in SQLite. Comparing a timezone-aware cutoff against naive stored values causes an inconsistent comparison. Using datetime.now() (naive, local time) keeps both sides consistent.

I also had to make changes to seed_data.py.

The original seed data was created when the database was first initialized — all the "recent" listening events (now - timedelta(minutes=10), etc.) were computed relative to that past moment. By the time Itried to test the feed, those events were 40+ hours old, so nothing fell within the 24-hour window and the feed returned an empty list. 

Re-seeding recalculates all timestamps relative to the current now, making the events fresh again. Without fresh seed data, the bug couldn't be reproduced at all.

***Verification After Fix***
![alt text](<Images/Bug_Verification_After_Fixes/2. Bug verification after fix (2).png>)

***Side Effect Checks***
No side effects occurred for Bug Fix #2. Here's why each related code path was safe:

get_activity_feed() — The other function in feed_service.py has no recency filter at all (it returns all friend events up to a limit). The RECENT_THRESHOLD constant and the cutoff variable are only used in get_friends_listening_now(), so get_activity_feed() is completely unaffected.

datetime.now() change — The naive datetime cutoff only affects the SQL comparison in get_friends_listening_now(). No other function in the codebase computes a cutoff this way.

seed_data.py changes — These only affect the local development database. Test files use in-memory SQLite databases (sqlite:///:memory:) that are seeded fresh for each test, so the seed data changes had zero impact on any test.

The regression test (test_get_friends_listening_now_excludes_stale_events) confirmed no side effects: all other feed tests continued to pass after the fix.


## 3. Root Cause Analysis for Bug Fix 4:  I got notified when a friend added my song to a playlist but not when they rated it

***Navigaation Strategy***

This bug is a problem with this route: it is notifying users when a friend adds their song, but not when they rate their song. 

users.py, with route:    GET/users/user_id/notifications --> notification_service.get_notifications(user_id)

***Reproducting the Error***

First, need to post a rating for that song.

![alt text](<Images/Bug_Verifications_Before_Fixes/3. Bug Verification  4 - post rating.png>)

Then verify user is not being notified of rating. 

![alt text](<Images/Bug_Verifications_Before_Fixes/3. Bug verification before (4).png>)

***Fix***

Add notification block to rate_song(user_id: str, song_id: str, score: int) -> Rating: in order to create notification for user.

***Verification After Fix***

After bug fix is made, both types of notification show up. 

![alt text](<Images/Bug_Verification_After_Fixes/3. Bug verification after fix (4).png>)

***Explanation***

The root cause of this bug was that rate_song() in notification_service.py saves the Rating record and commits, but never calls create_notification(). The notification step was simply never written. Compare with add_to_playlist() which calls create_notification() after its commit — rate_song() is missing that entire block.

***Side Effect Checks***
The fix for Bug #4 actually had two parts, each with its own side-effect analysis:

Part 1: Adding create_notification() to rate_song()

No side effects. rate_song() is only called from POST /songs/<song_id>/rate in songs.py. The notification block added mirrors exactly the same pattern already used in add_to_playlist() — same create_notification() call, same if song.shared_by != user_id guard. The rating creation and update logic was completely untouched. Verified by test_rate_song_creates_rating and test_rate_song_updates_existing_rating both continuing to pass.

Part 2: Replacing playlist.songs.append(song) with playlist_entries.insert()

This was the actual architectural fix that also resolved the two failing notification tests. The specific check worth noting: add_to_playlist() still uses playlist.songs (the relationship) to check membership (if song not in playlist.songs) and to count position (len(playlist.songs) + 1) — only the insert changed from using the relationship to a direct table insert. This was safe because:

get_playlist_songs() in playlist_service.py reads songs via a direct playlist_entries join query, not via playlist.songs — so it sees the newly inserted rows correctly regardless of how they were inserted.
get_playlist() (metadata only) is unaffected — it never touches songs.
All 49 tests passed after both changes.

## 4. Root Cause Analysis for Bug Fix 1:  My listening streak keeps resetting	

<!--TODO: Bug spotted: In update_listening_streak() on streak_service.py:67: elif days_since_last == 1 and today.weekday() != 6: The today.weekday() != 6 condition skips the streak increment on Sundays (weekday 6), which means listening on a Sunday after Saturday never extends the streak. This looks unintentional — the streak rules in the docstring make no mention of Sunday being excluded. -->

***Navigaation Strategy***

This bug is a problem with this route: it is notifying users when a friend adds their song, but not when they rate their song. 

songs.py, with route:    POST/songs/song_id/listen        --> streak_service.record_listening_event(user_id:, song_id). This function calls update_listening_streak() in streak_service.py, where we find the bug. 


***Reproducting the Error***

First, need to call POST/songs/song_id/listen from a valid user, set theirr streak to 2 with last_listened-at = yesterday, then POST today to show the reset. 

![alt text](<Images/Bug_Verifications_Before_Fixes/4. Bug verification before (1) .png>)

After psting a listenevent today (Sunday), the bug is clearly demonstrated: 
![alt text](<Images/Bug_Verifications_Before_Fixes/4. Bug verification before (1) - part 2.png>)

Bug resets to 1 instead of incrementing to 3. 

![alt text](<Images/Bug_Verifications_Before_Fixes/4.  Bug Result before (1) - part 3 .png>)


***Explanation***

The root cause of this bug in update_listening_streak() on streak_service.py elif days_since_last == 1 and today.weekday() != 6: The today.weekday() != 6 condition skips the streak increment on Sundays (weekday 6), which means listening on a Sunday after Saturday never extends the streak.

***Fix*** 

Fix is to change Line 73 in streak_service.py from
elif days_since_last == 1 and today.weekday() != 6: to 

elif days_since_last == 1 

After fix, we see that streak is now correctly set to 3. 

![alt text](<Images/Bug_Verification_After_Fixes/4. Bug verification after fix (1).png>)

***Side Effect Checks***
No side effects occurred for Bug Fix #1. Here's why each related code path was safe:

get_streak() — Read-only function that simply returns user.listening_streak. It doesn't call update_listening_streak() at all and was completely unaffected.

record_listening_event() — Unaffected. It just calls update_listening_streak(user, now) and then commits. The call signature and behavior for all non-Sunday days (Mon–Sat) is identical before and after the fix — the and today.weekday() != 6 condition was already True on those days, so the elif branch was already firing for them. Only Sunday behavior changed.

All other streak tests — test_streak_starts_at_1_for_new_user, test_streak_increments_on_consecutive_day, test_streak_does_not_double_count_same_day, and test_streak_resets_after_skipped_day all use non-Sunday dates. None were affected by the fix, and all continued to pass (confirmed by the Test Run 3 screenshot).

test_streak_increments_on_sunday — This test was previously failing and now passes — which is the intended outcome of the fix, not a side effect.

![alt text](<Images/Test_Files/3. Test Run 3 (After Bug Fix 1).png>)


## 5. Root Cause Analysis for Bug Fix 3: The same song keeps showing up twice in search	

With the requirements.txt, (as the code was given to u, I could not reproduce this bug. 

As the code currently stands, the error was not seen.

![alt text](<Images/Bug_Verifications_Before_Fixes/5. Bug verification before (3).png>)

According to Copilot, . SQLAlchemy 2.0's identity map is masking the bug. Here's what's happening:

The SQL level: The .outerjoin(song_tags, ...) without .distinct() generates:
```
SELECT song.* FROM song LEFT OUTER JOIN song_tags ON song.id = song_tags.song_id WHERE ...
```

***Navigaation Strategy***
The bug is a problem with this route: the same song keeps showing up twice in search.

songs.py, with route:    GET/songs/search                 --> search_service.search_songs(query: str)

Query returns all songs where the title or artist contains the query string (case-insensitive), along with their associated tags.

***Reproducting the Error***
I worked with AI to get the results I wanted to show that multiple results would be returned if they weren't hidden by 

![alt text](<Images/Bug_Verifications_Before_Fixes/5. Bug verification before fix (3) - part 2.png>)


***Explanation***
The bug is real — the SQL query returns 3 duplicate rows for "Crown Heights Anthem" (one per tag: rap, hip-hop, boom bap). SQLAlchemy 2.0's identity map just hides it from the API output.

***Fix***
The fix is to add .distinct() to line 28 in search_service.py. .distinct() tells SQLAlchemy to add SELECT DISTINCT to the SQL, so even though the join produces 3 rows for "Crown Heights Anthem", only 1 is returned.


***Side Effect Checks***

Two remaining failures both from the same root cause — playlist.songs.append(song) doesn't set the position (NOT NULL) column. 

The root cause: add_to_playlist uses playlist.songs.append(song) which uses the SQLAlchemy relationship and only inserts playlist_id, song_id, and added_at — silently omitting the position and added_by NOT NULL columns. The fix is to insert directly into playlist_entries:

Change to Bug Fix #4 (root cause) In notification_service.add_to_playlist position error	Replaced playlist.songs.append() with direct playlist_entries.insert(). 

No negative side effects occurred for Bug Fix #3. Here's why each related code path was safe:

get_song() — The other function in search_service.py uses db.session.get(Song, song_id) directly and is completely unaffected by the .distinct() addition.

Songs with 0 tags — The outer join produces 1 row (with NULL tag), .distinct() returns 1 row. Behavior unchanged. Confirmed by test_search_no_duplicates_no_tag_song passing.

Songs with 1 tag — The outer join produces 1 row, .distinct() returns 1 row. Behavior unchanged. Confirmed by test_search_no_duplicates_single_tag_song passing.

Tag data in responses — Tags are loaded via the Song relationship (lazy loading), not from the join itself. So adding .distinct() had zero impact on which tags appear in each song's response dict.

The only route that calls search_songs() is GET /songs/search in songs.py. No other service or route was touched.

All 8 search tests passed after the fix — test_search_returns_matching_songs, test_search_is_case_insensitive, test_get_song_returns_song_dict, and all the no-duplicates tests.

This change also fixed the two remaining failing tests. 

![alt text](<Images/Test_Files/4. Test Run 4 (After Bug Fix  3).png>)


### git log --oneline

![alt text](<Images/git log --oneline.png>)

## Stretch Feature: 

### Unit Testing 

I finished all 5 Bug Fixes.

I added two test files that didn't exist before: test_feed.py and test_notification.py.

I added 3 tests to test_playlists.py.

I added 3 tests for test_search.py 

I added a test in test_feed.py that would have caught this error: Bug Fix 2: Friends Listening Now shows people from yesterday test_get_friends_listening_now_excludes_stale_events(app).

I added two unit tests in test_notificatons.py that would have caught this error: Bug Fix 4: I got notified when a friend added my song to a playlist but not when they rated it. 

### Regression Testing
Copilot didn't differentiate between regression testing and the unit testing that I had already added, so hopefully the unit tests I added are sufficient for the stretch feature. 
