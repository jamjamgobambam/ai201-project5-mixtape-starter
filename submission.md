# Mixtape Codebase Map

## Project Overview

Mixtape is a Flask-based social music app where users share songs, build collaborative playlists, track listening streaks, and receive notifications about their friends' activities. The app follows a **layered architecture** with routes handling HTTP requests, services containing business logic, and SQLAlchemy models managing data persistence.

---

## Core Files & Their Roles

### Application Layer

| File | Role | Key Responsibility |
|------|------|-------------------|
| `app.py` | Flask factory | Creates the Flask app, initializes SQLAlchemy database, registers all route blueprints. Entry point for the application. |
| `models.py` | Data models | Defines all SQLAlchemy ORM entities (User, Song, Playlist, Rating, ListeningEvent, Notification, Tag) and their relationships. Central reference for data structure. |

### Route Layer (HTTP Entry Points)

| File | Endpoints | Purpose |
|------|-----------|---------|
| `routes/songs.py` | `/songs/search`, `/songs/<id>`, `/songs/<id>/rate`, `/songs/<id>/listen` | Handles song discovery (search), rating, and listening tracking. Delegates to search_service and notification_service. |
| `routes/playlists.py` | `/playlists/`, `/playlists/<id>`, `/playlists/<id>/songs` | Manages playlist CRUD and song management. Calls playlist_service for retrieval and notification_service for notifications. |
| `routes/users.py` | `/users/<id>`, `/users/<id>/streak`, `/users/<id>/notifications` | User profile, streak checking, and notification retrieval. Routes to streak_service and notification_service. |
| `routes/feed.py` | `/feed/<user_id>/listening-now`, `/feed/<user_id>/activity` | Shows recent friend activity. Uses feed_service for filtering and deduplication. |

### Service Layer (Business Logic) — **WHERE THE BUGS ARE**

| File | Key Functions | Purpose | Bug(s) |
|------|----------------|---------|--------|
| `services/streak_service.py` | `record_listening_event()`, `update_listening_streak()`, `get_streak()` | Tracks when users listen to songs and maintains their listening streak (consecutive days). Streak increments if user listens on consecutive days. | **Bug #1**: Streak resets on Sundays even if user listened yesterday |
| `services/feed_service.py` | `get_friends_listening_now()`, `get_activity_feed()` | "Friends Listening Now" shows recent song activity from friends. Filters events by recency and deduplicates (one song per friend). | **Bug #2**: Shows friends from 24 hours ago, not just today |
| `services/search_service.py` | `search_songs()`, `get_song()` | Searches songs by title or artist (case-insensitive). Includes tag information. | **Bug #3**: Returns duplicate songs if they have multiple tags |
| `services/notification_service.py` | `create_notification()`, `add_to_playlist()`, `rate_song()`, `get_notifications()`, `mark_as_read()` | Creates and retrieves notifications when friends interact with shared songs. Notifications triggered by playlist additions and ratings. | **Bug #4**: Missing notification when song is rated |
| `services/playlist_service.py` | `create_playlist()`, `get_playlist_songs()`, `get_playlist()`, `get_user_playlists()` | Manages playlist lifecycle and retrieves songs in order. Tracks song position within playlists. | **Bug #5**: Last song in playlist is never returned |

### Test & Data Setup

| File | Purpose |
|------|---------|
| `seed_data.py` | Populates database with test data (users, songs, playlists, ratings, listening events). Useful for manual testing and reproduction. |
| `tests/` | Unit tests for search, playlists, and streak logic. Can be run with `pytest tests/`. |

---

## Data Model Overview

### Core Entities & Relationships

```
User
├── listening_streak (int) — consecutive days of listening
├── last_listened_at (datetime) — timestamp of most recent listen
├── friends (many-to-many) — symmetric friendship relationship
├── shared_songs (one-to-many) → Song
├── ratings (one-to-many) → Rating
├── listening_events (one-to-many) → ListeningEvent
├── notifications (one-to-many) → Notification
└── playlists (one-to-many) → Playlist

Song
├── title, artist, album, genre
├── shared_by (FK) → User (who shared it)
├── shared_at (datetime)
├── ratings (one-to-many) → Rating
├── listening_events (one-to-many) → ListeningEvent
└── tags (many-to-many) → Tag

Rating
├── user_id (FK) → User (who rated)
├── song_id (FK) → Song (what was rated)
├── score (int 1–5)
└── rated_at (datetime)

ListeningEvent
├── user_id (FK) → User (who listened)
├── song_id (FK) → Song
└── listened_at (datetime)

Playlist
├── name, created_by (FK) → User
├── is_collaborative (bool)
├── songs (many-to-many via playlist_entries)
└── playlist_entries associates songs with position and added_by

Notification
├── user_id (FK) → User (recipient)
├── notification_type (string) — e.g., "song_added_to_playlist", "song_rated"
├── body (text) — human-readable message
├── read (bool)
└── created_at (datetime)
```

---

## Feature: Song Sharing & Notifications

### User Story

*When User A shares a song and User B rates or adds it to a playlist, User A should be notified.*

### Data Flow Trace

#### Step 1: Song Rating Flow

```
User B sends: POST /songs/<song_id>/rate
  body: {"user_id": "user_b_id", "score": 4}
         ↓
routes/songs.py → rate() endpoint
         ↓
Calls: notification_service.rate_song(user_b_id, song_id, 4)
         ↓
services/notification_service.py → rate_song()
  ├─ Validates user exists
  ├─ Validates song exists
  ├─ Creates or updates Rating object
  └─ [BUG #4: Missing notification for the song's original sharer]
         ↓
Response: 201 Created with Rating JSON
         ↓
[EXPECTED but missing]: Notification created for User A (song's sharer)
  ├─ notification_type: "song_rated"
  ├─ body: "User B rated your song 'Song Title' 4 stars"
  └─ Inserted into Notification table
```

#### Step 2: Add Song to Playlist (Working Reference)

```
User B sends: POST /playlists/<playlist_id>/songs
  body: {"song_id": "song_id", "added_by": "user_b_id"}
         ↓
routes/playlists.py → add_song() endpoint
         ↓
Calls: notification_service.add_to_playlist(playlist_id, song_id, user_b_id)
         ↓
services/notification_service.py → add_to_playlist()
  ├─ Validates all entities exist
  ├─ Appends song to playlist.songs
  ├─ Commits to database
  └─ [WORKING]: Checks if song.shared_by != added_by_user_id
              └─ Creates notification:
                 create_notification(
                   user_id=song.shared_by,
                   notification_type="song_added_to_playlist",
                   body=f"{user_b_username} added your song '{title}' to playlist..."
                 )
         ↓
Response: 201 Created
         ↓
[RESULT]: User A receives notification about their song being added
```

#### Step 3: Notification Retrieval

```
User A sends: GET /users/<user_a_id>/notifications
              ↓
routes/users.py → notifications() endpoint
              ↓
Calls: notification_service.get_notifications(user_a_id, unread_only=False)
              ↓
services/notification_service.py → get_notifications()
  ├─ Queries Notification table where user_id = user_a_id
  ├─ Orders by created_at DESC (newest first)
  └─ Converts to list of dicts
              ↓
Response: 200 OK with list of notifications
```

**Pattern to notice**: `add_to_playlist` creates a notification for the song's original sharer (lines 65-70). The `rate_song` function should follow the same pattern but doesn't (this is Bug #4).

---

## Architectural Patterns Observed

### 1. **Service Layer Abstraction**

All business logic is isolated in `services/`. Routes never directly manipulate the database; they delegate to services:

```python
# In routes/songs.py (thin endpoint)
@songs_bp.route("/<song_id>/rate", methods=["POST"])
def rate(song_id):
    user_id = data.get("user_id")
    score = data.get("score")
    rating = rate_song(user_id, song_id, int(score))  # ← All logic is here
    return jsonify(rating.to_dict()), 201

# In services/notification_service.py (fat service)
def rate_song(user_id: str, song_id: str, score: int) -> Rating:
    # Database queries, validation, business rules
    existing = db.session.query(Rating).filter_by(...).first()
    ...
```

**Implication for debugging**: If an endpoint is broken, trace it to its service function. Don't modify routes; look at the service implementation.

### 2. **Many-to-Many Relationships via Association Tables**

Playlists use `playlist_entries` to store both the song reference AND metadata (position, added_by):

```python
# In models.py
playlist_entries = db.Table(
    "playlist_entries",
    db.Column("playlist_id", ...),
    db.Column("song_id", ...),
    db.Column("position", db.Integer, nullable=False),  # ← Track order
    db.Column("added_by", ..., nullable=False),
)

# In services/playlist_service.py
.join(playlist_entries, Song.id == playlist_entries.c.song_id)
.filter(playlist_entries.c.playlist_id == playlist_id)
.order_by(asc(playlist_entries.c.position))
```

**Implication**: When querying playlists, you must join through the association table. Simple `.all()` won't preserve order.

### 3. **Notification as First-Class Event**

Whenever a user performs an action on another user's shared content, a Notification is created:

```python
# Shared pattern in notification_service.py:

def add_to_playlist(playlist_id, song_id, added_by_user_id):
    song = db.session.get(Song, song_id)  # Get context
    adder = db.session.get(User, added_by_user_id)
    # Perform action
    playlist.songs.append(song)
    # Notify the original sharer
    if song.shared_by != added_by_user_id:
        create_notification(
            user_id=song.shared_by,
            notification_type="song_added_to_playlist",
            body=f"{adder.username} added your song '{song.title}' ..."
        )
```

**Implication**: Look for missing notifications by comparing against existing patterns.

### 4. **Timestamp-Based Filtering**

Several services filter by timestamps to show "current" activity:

```python
# In feed_service.py
RECENT_THRESHOLD = timedelta(hours=24)
cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD
recent_events = db.session.query(ListeningEvent).filter(
    ListeningEvent.listened_at >= cutoff
)
```

**Implication**: Be careful about timezones and the definition of "recent" — is it 24 hours or today's calendar day?

### 5. **Deduplication Logic**

Some endpoints return deduplicated results (e.g., feed shows one song per friend):

```python
# In feed_service.py
seen_friends = set()
result = []
for event in recent_events:
    if event.user_id not in seen_friends:  # ← Skip if already seen
        seen_friends.add(event.user_id)
        result.append({...})
```

**Implication**: Search and feed results need deduplication. Check if duplicates are coming from the database query or the Python code.

---

## Key Data Flow Sequences

### Listening Streak Update Sequence

```
User listens to song
  ↓
POST /songs/<song_id>/listen {user_id}
  ↓
routes/songs.py → listen()
  ↓
streak_service.record_listening_event(user_id, song_id)
  ├─ Create ListeningEvent
  ├─ Call update_listening_streak(user, now)
  │  └─ Check days since last_listened_at
  │     ├─ If None: streak = 1
  │     ├─ If 0 days: no change
  │     ├─ If 1 day: streak += 1 [BUG: checks weekday]
  │     └─ If 2+ days: streak = 1
  └─ Commit and return event
  ↓
Response: ListeningEvent JSON
```

### Playlist Song Order Preservation

```
Multiple users add songs to same collaborative playlist
  ↓
Each add_to_playlist() call increments position in playlist_entries
  ↓
GET /playlists/<id>/songs
  ↓
playlist_service.get_playlist_songs(playlist_id)
  ├─ Query: SELECT Song...
  ├─ JOIN playlist_entries
  ├─ ORDER BY playlist_entries.position ASC
  └─ Return songs[:-1] [BUG: drops last song]
  ↓
Response: Song list (with last song missing)
```

---

## **Reproducing the bugs**
To reproduce the bugs I created the ``test_bugs.py`` python script which can be found on the github repo
Here is the output:
```
============================================================
REPRODUCING BUGS #1, #2, #3
============================================================

Bug #1 - Streak on Sunday: 1
  Expected: 2, Actual: 1
  ✓ Bug present: True

Bug #3 - Search duplicates:
  Raw SQL rows: 2
  Python results: 1
  Expected: 1 row, Actual: 2 rows
  ✓ Bug present: True

Bug #2 - Yesterday's friends show:
  Event time: 2026-07-05 17:19:06.546366+00:00
  Current time: 2026-07-06 16:19:06.562411+00:00
  Hours old: ~23 hours
  Threshold: 24 hours
  Expected: 0, Actual: 1
  ✓ Bug present: True
  Friend appeared: bob_2232f43e
  (They shouldn't appear—listened yesterday, not 'now')

============================================================
```

### Bug #1 – Listening streak resets on Sunday

**How I reproduced it:**

1. Created a new test user with a listening streak of `1`.
2. Set the user's `last_listened_at` timestamp to one day before the current date.
3. Called `update_listening_streak()` while passing a date that falls on **Sunday (January 7, 2024)**.
4. Verified that the user's listening streak remained at `1` instead of increasing to `2`.

This reproduces the bug because listening activity occurred on consecutive days, so the streak should have continued instead of resetting.

---

### Bug #2 – Friends from yesterday appear in "Listening Now"

**How I reproduced it:**

1. Created two users, **Alice** and **Bob**.
2. Added Bob as one of Alice's friends.
3. Created a song shared by Alice.
4. Created a `ListeningEvent` for Bob with a timestamp approximately **23 hours before the current time**, placing it within the previous calendar day but still inside a 24-hour window.
5. Called `get_friends_listening_now(alice.id)`.
6. Observed that Bob was returned in the results even though his listening activity occurred **yesterday** rather than "now."

This reproduces the bug because the feature should only display users who are currently listening, not users whose listening event happened on the previous day.

---

### Bug #3 – Songs with multiple tags produce duplicate search rows

**How I reproduced it:**

1. Created a new test user.
2. Created a new song associated with that user.
3. Attached two tags (`indie` and `rock`) to the same song.
4. Executed the song search using `search_songs()` with the song title.
5. Ran a raw SQL query against the `song` and `song_tags` tables to verify the underlying query results.

The raw SQL query returned **two rows** for the same song because the join produced one row for each matching tag, while SQLAlchemy returned only one Python object by deduplicating entities with the same primary key. This confirmed that the duplicate rows exist in the query itself even though the ORM hides them in the final result.

# Root Cause Analysis: Listening Streak Bug Fixes

---

## Issue #1: My listening streak keeps resetting

**Affected service:** `streak_service.py`

### 1. Issue Number and Title
**Bug #1:** My listening streak keeps resetting

**Description:** Users report that their listening streak resets to 1 even when they listen to songs on consecutive days, specifically when the second day is a Sunday.

---

### 2. How I Reproduced It

**Steps to reproduce:**

1. Create a test user with a listening streak.
2. Set the user's `last_listened_at` to Saturday at any time.
3. Record a listening event on Sunday.
4. Check the user's streak via `GET /users/<user_id>/streak`.

**Expected behavior:** Streak should increment from 1 to 2 (consecutive days).

**Actual behavior:** Streak remains at 1 (incorrectly reset).

**Data condition that triggers it:** The listening event must occur on a **Sunday** immediately following a **Saturday** listen. On any other consecutive days (Mon→Tue, Fri→Sat, Sun→Mon), the streak increments correctly.

**Verification test output:**
```
Bug #1 - Streak on Sunday: 1
  Expected: 2, Actual: 1
  ✓ Bug present: True
```

---

### 3. How I Found the Root Cause

**Navigation path:**

1. Started with `services/streak_service.py` (identified by project README as the bug location)
2. Read the `update_listening_streak()` function (lines 42–78) to understand the streak logic
3. Reviewed the documented streak rules in the function's docstring (lines 46–50):
   - "If the user listened yesterday: streak increments by 1."
   - No mention of any day-of-week exceptions
4. Examined the conditional logic at line 73:
   ```python
   elif days_since_last == 1 and today.weekday() != 6:
       user.listening_streak += 1
   ```
5. **Key insight:** The condition includes `today.weekday() != 6`, which means "only increment if today is NOT Sunday"
   - Python's `datetime.weekday()` returns 6 for Sunday
   - So when `today` is Sunday, the condition `!= 6` evaluates to `False`, blocking the increment
6. Cross-checked with `tests/test_streaks.py` line 83, which has a test `test_streak_increments_on_sunday()` that explicitly tests this scenario and expects the streak to increment to 2
7. **Confirmed root cause:** The weekday check is preventing streak increment on Sunday despite being consecutive days

---

### 4. The Root Cause

**Precise explanation:**

The `update_listening_streak()` function in `streak_service.py` contains a conditional at line 73 that checks both:
1. Whether one day has passed since the last listen (`days_since_last == 1`)
2. Whether today is NOT Sunday (`today.weekday() != 6`)

**The bug:** When a user listens on consecutive days where the second day is Sunday, the second condition fails. Python's `datetime.weekday()` method returns an integer where Sunday = 6. The expression `today.weekday() != 6` evaluates to `False` when `today` is Sunday, causing the entire `elif` condition to short-circuit and fail. As a result, the code falls through to the `else` block (line 75–76), which unconditionally resets the streak to 1 instead of incrementing it.

**Why the weekday check exists:** Unknown—it contradicts both the function's documented behavior and the existing test suite. The docstring explicitly states "If the user listened yesterday: streak increments by 1" with no exception for Sundays. The test at line 83 of `test_streaks.py` confirms the expected behavior is to increment the streak on Saturday→Sunday transitions.

**The gap:** The streak logic was written to enforce consecutive-day increments, but an unnecessary weekday check prevents that logic from working correctly on Sundays, treating them as a special case when they should not be.

---

### 5. Fix and Side-Effect Check

**The fix:**

**Location:** `services/streak_service.py`, lines 73–74

**Before:**
```python
elif days_since_last == 1 and today.weekday() != 6:
    user.listening_streak += 1
```

**After:**
```python
elif days_since_last == 1:
    user.listening_streak += 1
```

**Why this fixes the root cause:** Removing the `and today.weekday() != 6` check allows the streak to increment on ANY consecutive day, including Sundays. The logic now correctly implements the documented rule: "If the user listened yesterday: streak increments by 1."

**Side-effect check—verified other functionality:**

1. **Same-day double-counting prevention** (lines 70–72):
   - Test: User listens twice on the same day
   - Before fix: Streak stays at 1 ✓
   - After fix: Streak stays at 1 ✓
   - No regression

2. **Gap-day streak reset** (lines 75–76):
   - Test: User listens on Monday, skips Tuesday, listens on Wednesday
   - Before fix: Streak resets to 1 ✓
   - After fix: Streak resets to 1 ✓
   - No regression

3. **Initial streak start** (lines 58–61):
   - Test: First-time user listens
   - Before fix: Streak starts at 1 ✓
   - After fix: Streak starts at 1 ✓
   - No regression

4. **Consecutive days on other weekdays** (lines 73–74):
   - Test: User listens Monday then Tuesday
   - Before fix: Streak increments to 2 ✓
   - After fix: Streak increments to 2 ✓
   - No regression

5. **Existing test suite:**
   - The existing test `test_streak_increments_on_sunday()` in `tests/test_streaks.py` (line 83) now passes
   - All other streak tests continue to pass
   - No breaking changes

**Conclusion:** The fix is minimal, targeted, and does not affect any other functionality. It removes an erroneous condition without altering the core logic or introducing new branches.

---

## Summary Table

| Aspect | Details |
|--------|---------|
| **Bug Title** | My listening streak keeps resetting |
| **Root Cause** | Unnecessary `today.weekday() != 6` check blocks streak increment on Sundays |
| **Fix Applied** | Removed the weekday condition from line 73 |
| **Lines Changed** | 1 line modified in `services/streak_service.py` |
| **Regressions Checked** | 5 related scenarios; all pass |
| **Commit Message** | `fix: remove Sunday weekday check from streak increment logic` |


# Root Cause Analysis: Bug #2 — Friends Listening Now Shows People from Yesterday

---

## Issue #2: Friends Listening Now shows people from yesterday

**Affected service:** `feed_service.py`

### 1. Issue Number and Title
**Bug #2:** Friends Listening Now shows people from yesterday

**Description:** The "Friends Listening Now" feed displays friends who listened to music in the past 24 hours, not just friends listening today. Users see friends in the "now" feed even though those friends listened yesterday and may not be active today.

---

### 2. How I Reproduced It

**Steps to reproduce:**

1. Create two users (Alice and Bob) and establish a friendship.
2. Have Bob listen to a song yesterday within the 24-hour window but not today.
3. Wait to ensure the listening event is more than 24 hours old.
4. Call the endpoint: `GET /feed/<alice_id>/listening-now`

**Specific data condition:**

Set Bob's listening event timestamp to be:
- **More than 24 hours ago:** Event doesn't appear (expected)
- **Exactly 24 hours ago:** Event disappears at the 24-hour boundary (edge case)
- **Less than 24 hours ago:** Event still appears even if from yesterday (BUG)

**Critical example that triggers the bug:**
- Bob listens: **Yesterday at 4 PM**
- Alice checks: **Today at 3 PM** (23 hours have passed)
- **Expected result:** Bob doesn't appear (different calendar day)
- **Actual result:** Bob appears (clock window hasn't expired yet)

**Verification test output:**
```
Scenario 2: Friend listened 23 hours ago (yesterday 4 PM, check at 3 PM today)
  Listened at: 2026-07-05 17:41:58+00:00
  Old logic (24-hour window): True      ← Friend APPEARS (BUG)
  New logic (calendar day):   False     ← Friend EXCLUDED (FIXED)
  Expected: False (friend didn't listen today)
  ✓ FIXED: Correctly excluded (BUG was here)
```

---

### 3. the Root Cause

**Navigation path:**

1. Started with the problem description: "Friends Listening Now shows people from yesterday"
2. Identified the affected service: `services/feed_service.py` (from README)
3. Examined the `get_friends_listening_now()` function (lines 16–62)
4. Found the filtering logic at lines 32 and 42:
   ```python
   cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD  # Line 32
   ListeningEvent.listened_at >= cutoff,                   # Line 42
   ```
5. Traced back to the threshold definition at line 13:
   ```python
   RECENT_THRESHOLD = timedelta(hours=24)
   ```
6. **Key realization:** The constant uses `timedelta(hours=24)` which is a clock-based time window, not a calendar-day check
7. **Mental test:** If a friend listened at 4 PM yesterday and you check at 3 PM today:
   - Time elapsed: 23 hours
   - 24-hour window check: `23 < 24` → Still within threshold → INCLUDE (wrong!)
   - Calendar day check: `different date()` → EXCLUDE (correct!)
8. **Confirmed the gap:** The function calculates `cutoff = now - 24 hours` instead of `cutoff = start of today`, causing it to include events from yesterday that happened less than 24 hours ago
9. Verified by checking if there were any tests for this behavior (none found for calendar-day correctness)
10. **Final confirmation:** The feature name "Listening **Now**" implies "currently listening" (today), not "listened within 24 hours"

---

### 4. The Root Cause

**Precise explanation:**

The `get_friends_listening_now()` function uses a **clock-based time window** instead of a **calendar-date boundary**.

**The problematic code (line 13):**
```python
RECENT_THRESHOLD = timedelta(hours=24)
```

**How it's used (lines 32 and 42):**
```python
cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD  # e.g., now minus 24 hours
...
ListeningEvent.listened_at >= cutoff  # Include if within 24-hour window
```

**Why this is wrong:**

A `timedelta(hours=24)` creates a hard 24-hour clock-based cutoff. This means:
- If the current time is July 6 at 3 PM UTC
- `cutoff = July 5 at 3 PM UTC`
- Any event from July 5 at 3:01 PM UTC to July 6 at 3 PM UTC is **included**
- An event from July 5 at 3:01 PM is **not** on today's calendar date, but it's still **within the 24-hour window**

**The semantic mismatch:**
- Function name: `get_friends_listening_now()` — implies "right now" / "today"
- Feature semantics: "Friends Listening Now" — users expect to see who's active today
- Actual behavior: Shows anyone who listened within the past 24 hours, including yesterday
- Expected behavior: Shows only friends who listened on today's calendar date

**The impact:**
A user checking at 2 PM on Monday will see friends who listened at 3 PM on Sunday (yesterday), even though it's not "now" — it's the past day. The 23-hour-old listen still passes the `>= cutoff` check.

---

### 5. Fix and Side-Effect Check

**The fix:**

**Location:** `services/feed_service.py`, lines 13–32 (removed `RECENT_THRESHOLD`, replaced clock-based cutoff with calendar-date boundary)

**Before:**
```python
RECENT_THRESHOLD = timedelta(hours=24)

def get_friends_listening_now(user_id: str) -> list[dict]:
    ...
    cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD
    recent_events = (
        db.session.query(ListeningEvent)
        .filter(
            ListeningEvent.user_id.in_(friend_ids),
            ListeningEvent.listened_at >= cutoff,  # Clock-based window
        )
        ...
```

**After:**
```python
def get_friends_listening_now(user_id: str) -> list[dict]:
    ...
    # Calculate the start of today (midnight UTC)
    now = datetime.now(timezone.utc)
    today_start = datetime.combine(now.date(), datetime.min.time()).replace(tzinfo=timezone.utc)
    
    recent_events = (
        db.session.query(ListeningEvent)
        .filter(
            ListeningEvent.user_id.in_(friend_ids),
            ListeningEvent.listened_at >= today_start,  # Calendar day boundary
        )
        ...
```

**Why this fixes the root cause:**

1. **Removes the clock-based window:** No more `RECENT_THRESHOLD` constant or `now - timedelta(hours=24)` calculation
2. **Implements calendar-day logic:** Uses `datetime.combine(now.date(), datetime.min.time())` to get midnight UTC of today
3. **Fixes the semantic mismatch:** Now correctly shows only events from today's calendar date
4. **Correct boundary:** `listened_at >= today_start` includes events from 00:00:01 today onwards, excluding all of yesterday

**How the fix handles edge cases:**

| Scenario | Old Logic | New Logic | Correct? |
|----------|-----------|-----------|----------|
| Friend listened 5 min ago | Include | Include | ✓ |
| Friend listened this morning (8 AM) | Include | Include | ✓ |
| Friend listened 23 hours ago (yesterday) | **Include** (BUG) | **Exclude** | ✓ |
| Friend listened exactly 24 hours ago | Exclude | Exclude | ✓ |
| Friend listened yesterday at 11:59 PM | Include | Exclude | ✓ |
| Friend listened today at 00:00:01 | Include | Include | ✓ |

**Side-effect check—verified related functionality:**

1. **`get_activity_feed()` is unaffected** (lines 65–105):
   - This function intentionally has NO time filter
   - Docstring states: "Returns the most recent N events regardless of when they happened"
   - Verified: No changes needed, no regressions
   - Before/After: Both return unlimited recent events ✓

2. **Route handlers are unaffected** (`routes/feed.py`):
   - `GET /feed/<user_id>/listening-now` now returns today's events only ✓
   - `GET /feed/<user_id>/activity` still returns unlimited recent events ✓
   - Before/After: Routes continue to work correctly ✓

3. **Deduplication logic is unaffected** (lines 48–61):
   - Shows only the most recent song per friend
   - Verified: Still works with calendar-day filtered events ✓

4. **Friendship queries are unaffected**:
   - Still correctly fetches the user's friend list ✓
   - Still correctly filters events by friend_id ✓

5. **Database query structure is unaffected**:
   - Still uses SQLAlchemy ORM correctly ✓
   - Still orders by `desc(ListeningEvent.listened_at)` ✓
   - Still deduplicates by tracking `seen_friends` ✓

6. **Timezone handling is correct**:
   - Uses `timezone.utc` consistently ✓
   - `now.date()` respects UTC timezone ✓
   - `datetime.min.time()` combined with UTC creates correct midnight boundary ✓

**Conclusion:** The fix is minimal, targeted, and handles the semantic change correctly. The calendar-day boundary replaces the clock-based window without breaking any other functionality. The activity feed remains unaffected because it intentionally has no time filtering.

---

## Summary Table

| Aspect | Details |
|--------|---------|
| **Bug Title** | Friends Listening Now shows people from yesterday |
| **Root Cause** | Clock-based 24-hour time window instead of calendar-day boundary |
| **Fix Applied** | Replace `cutoff = now - timedelta(hours=24)` with calendar-day check |
| **Lines Changed** | 3 lines in `services/feed_service.py` (removed 1, modified 2) |
| **Regressions Checked** | 6 edge cases + 3 related functions; all pass |
| **Commit Message** | `fix: change friends listening now to use calendar day boundary instead of 24-hour window` |

---

## Test Output Proof

```
Scenario 2: Friend listened 23 hours ago (yesterday 4 PM, check at 3 PM today)
  Listened at: 2026-07-05 17:41:58.276090+00:00
  Old logic (24-hour window): True      ← BUG: Friend incorrectly appears
  New logic (calendar day):   False     ← FIXED: Friend correctly excluded
  Expected: False (friend didn't listen today)
  ✓ FIXED: Correctly excluded (BUG was here)
```