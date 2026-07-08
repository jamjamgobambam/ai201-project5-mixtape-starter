# Project 5: Mixtape Bug Hunt Submission

## AI Usage

I used ChatGPT as a debugging assistant throughout this project. Rather than asking it to solve the bugs directly, I used it to understand the codebase, trace execution paths, analyze failing behavior, and verify potential fixes before making changes.

### Example 1: Understanding the listening streak bug

I used ChatGPT to trace the execution flow for the listening streak feature. It helped me follow the request from the `/songs/<song_id>/listen` route to `record_listening_event()` and then to `update_listening_streak()` in `services/streak_service.py`. After identifying the suspicious Sunday condition, I ran the provided tests to reproduce the bug, applied a one-line fix, and reran both the streak tests and the full test suite to verify that the issue was resolved without introducing regressions.

### Example 2: Analyzing playlist retrieval

I also used ChatGPT to understand how playlist retrieval worked. We traced the request from the playlist route to `get_playlist_songs()` in `services/playlist_service.py`, where the final song in every playlist was being excluded because of list slicing. After identifying the cause, I removed the slice, reran the playlist tests, and then executed the full test suite to confirm that all existing functionality continued to work correctly.

### Independent verification

I verified every suggested fix before committing it. For each bug, I inspected the code myself, reproduced the behavior where possible, ran the provided tests before and after making changes, and only committed fixes that were confirmed to work. I also avoided making unnecessary changes until I had evidence that a specific issue actually existed.


## Codebase Map

The Mixtape application follows a layered architecture where HTTP requests are handled by routes, business logic is implemented in services, and data is stored and retrieved through SQLAlchemy models.

### Main Components

- **app.py**
  - Creates the Flask application.
  - Configures the database.
  - Registers all route blueprints.

- **models.py**
  - Defines the SQLAlchemy models (`User`, `Song`, `Playlist`, `ListeningEvent`, `Rating`, `Notification`, and `Tag`).
  - Defines the association tables used for friendships, playlist entries, and song tags.

- **routes/**
  - Receives HTTP requests.
  - Validates request data.
  - Calls the appropriate service function.
  - Returns JSON responses.

- **services/**
  - Contains the application's business logic.
  - Performs database queries and updates.
  - Implements the behavior for playlists, search, notifications, listening streaks, and activity feeds.

### Request Flow

The application follows this general flow:

```
Client Request
      ↓
Route (routes/)
      ↓
Service (services/)
      ↓
SQLAlchemy Models (models.py)
      ↓
Service
      ↓
Route
      ↓
JSON Response
```

### Bug Navigation Examples

- **Issue #1 (Listening Streak)**
  - `/songs/<song_id>/listen`
  - `routes/songs.py`
  - `services/streak_service.py`
  - `models.py`

- **Issue #2 (Friends Listening Now)**
  - `/feed/<user_id>/listening-now`
  - `routes/feed.py`
  - `services/feed_service.py`
  - `models.py`

- **Issue #3 (Duplicate Search Results)**
  - `/songs/search`
  - `routes/songs.py`
  - `services/search_service.py`
  - `models.py`

- **Issue #4 (Rating Notifications)**
  - `/songs/<song_id>/rate`
  - `routes/songs.py`
  - `services/notification_service.py`
  - `models.py`

- **Issue #5 (Playlist Retrieval)**
  - `/playlists/<playlist_id>/songs`
  - `routes/playlists.py`
  - `services/playlist_service.py`
  - `models.py`


## Root Cause Analysis

### Issue #1 – My listening streak keeps resetting

#### Reproduction Steps

1. Run the listening streak tests using `pytest tests/test_streaks.py`.
2. Observe that `test_streak_increments_on_sunday` fails.
3. The streak resets to 1 instead of increasing to 2 when a user listens on Saturday and then Sunday.

#### Navigation Strategy

I started by reading `routes/songs.py` to find which endpoint handled listening events. The `/songs/<song_id>/listen` route called `record_listening_event()` in `services/streak_service.py`. From there, I traced the flow into `update_listening_streak()`, where the streak calculation logic was implemented.

#### Root Cause Explanation

The streak increment condition incorrectly prevented streaks from increasing when the current day was Sunday.

```python
elif days_since_last == 1 and today.weekday() != 6:
```

Since `weekday() == 6` represents Sunday, the condition evaluated to false even when the user had listened on consecutive days (Saturday → Sunday). As a result, the streak reset instead of incrementing.

#### Fix Description

I removed the unnecessary Sunday check so that the streak increments whenever exactly one calendar day has passed.

```python
elif days_since_last == 1:
```

This correctly treats Sunday like every other day of the week.

#### Side-Effect Check

After making the change, I reran both `pytest tests/test_streaks.py` and the complete test suite (`pytest tests/`). All tests passed, confirming that consecutive-day streaks still worked correctly while fixing the Sunday edge case.

### Issue #2 – Friends Listening Now shows people from yesterday

#### Reproduction Steps

1. Review the implementation of `get_friends_listening_now()` in `services/feed_service.py`.
2. Observe that the feed filters listening events using a rolling 24-hour window.
3. A friend who listened late yesterday but within the last 24 hours would still appear in the "Listening Now" feed, even though they were not listening today.

#### Navigation Strategy

I traced the request from the `/feed/<user_id>/listening-now` endpoint in `routes/feed.py` to `get_friends_listening_now()` in `services/feed_service.py`. I then followed the query used to retrieve recent listening events and examined how the cutoff time was calculated.

#### Root Cause Explanation

The service defined "recent" as the last 24 hours.

```python
cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD
```

This rolling time window included listening events from the previous day if they occurred within the last 24 hours. As a result, users who listened yesterday could incorrectly appear in the "Listening Now" feed.

#### Fix Description

I changed the cutoff time to the beginning of the current day instead of using a rolling 24-hour window.

```python
now = datetime.now(timezone.utc)
cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
```

This ensures that only listening events from the current day are included in the "Listening Now" feed.

#### Side-Effect Check

After making the change, I ran the full test suite using `pytest tests/`. All 13 tests continued to pass, confirming that the modification did not introduce regressions in other parts of the application.

### Issue #3 – The same song keeps showing up twice in search

#### Reproduction Steps

1. Review the implementation of `search_songs()` in `services/search_service.py`.
2. Observe that the query performs an outer join between the `Song` table and the `song_tags` association table.
3. Songs with multiple tags can produce multiple joined rows, causing duplicate search results under certain conditions.

#### Navigation Strategy

I started from the `/songs/search` endpoint in `routes/songs.py`, which calls `search_songs()` in `services/search_service.py`. I then examined the SQLAlchemy query to understand how songs and their associated tags were retrieved during a search.

#### Root Cause Explanation

The search query performed an outer join with the `song_tags` table.

```python
.outerjoin(song_tags, Song.id == song_tags.c.song_id)
```

Joining the `song_tags` table can produce multiple rows for the same song when a song has multiple associated tags. Adding `.distinct()` ensures each song is returned only once, regardless of the number of matching joined rows.

#### Fix Description

I explicitly added `.distinct()` to the query.

```python
.distinct()
```

This guarantees that each matching song is returned only once, regardless of how many tag records are associated with it.

#### Side-Effect Check

After adding `.distinct()`, I ran both the search tests (`pytest tests/test_search.py`) and the complete test suite (`pytest tests/`). All tests continued to pass, confirming that the change preserved existing functionality while preventing duplicate search results.

### Issue #4 – I got notified when a friend added my song to a playlist but not when they rated it

#### Reproduction Steps

1. Review the implementation of `rate_song()` in `services/notification_service.py`.
2. Compare its behavior with `add_to_playlist()`.
3. Observe that adding a song to a playlist creates a notification, while rating a song does not.

#### Navigation Strategy

I traced the request from the `/songs/<song_id>/rate` endpoint in `routes/songs.py` to the `rate_song()` function in `services/notification_service.py`. I then compared this implementation with `add_to_playlist()`, which already generated notifications.

#### Root Cause Explanation

The `rate_song()` function correctly created or updated a rating, but it never called `create_notification()`. As a result, the owner of the song was never informed when another user rated their song.

#### Fix Description

After saving the rating, I added a call to `create_notification()` whenever someone rated another user's shared song. The notification includes the rater's username, the song title, and the rating score.

#### Side-Effect Check

After implementing the notification logic, I ran the complete test suite using `pytest tests/`. All tests continued to pass, confirming that the additional notification logic did not affect the existing rating functionality.

### Issue #5 – The last song in a playlist never shows up

#### Reproduction Steps

1. Run `pytest tests/test_playlists.py`.
2. Observe that the playlist tests fail because only four songs are returned when the playlist contains five.
3. The returned song list is always missing the final entry.

#### Navigation Strategy

I traced the playlist retrieval flow from `/playlists/<playlist_id>/songs` in `routes/playlists.py` to `get_playlist_songs()` in `services/playlist_service.py`. I then examined how the ordered list of songs was constructed before being returned.

#### Root Cause Explanation

The playlist query correctly retrieved every song, but the final return statement removed the last element using list slicing.

```python
return [song.to_dict() for song in songs[:-1]]
```

Because `songs[:-1]` excludes the last item in the list, every playlist was returned with one song missing.

#### Fix Description

I removed the unnecessary slice and returned the complete list of songs.

```python
return [song.to_dict() for song in songs]
```

This allows every song in the playlist to be returned in the correct order.

#### Side-Effect Check

After making the change, I reran `pytest tests/test_playlists.py` and then the full test suite (`pytest tests/`). All 13 tests passed, confirming that playlist ordering and retrieval both worked correctly.