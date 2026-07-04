# Mixtape Bug Hunt Submission

## AI Usage
I used AI tools mainly during codebase orientation and debugging. I asked for summaries of the service modules and for help tracing how a song flows from a route into the service layer, which was helpful for understanding the app structure quickly. I also used AI to reason about the likely root causes once I had narrowed a bug to a specific function. In each case, I verified the explanation by reading the relevant code and running the targeted tests myself before making any change.

## Codebase Map
The app is organized around a Flask app factory in app.py and a SQLAlchemy data model in models.py. The routes package contains endpoint handlers for songs, playlists, users, and the feed. Each route delegates to a service module in services/, and those services contain the business logic and database access. For example, when a song is rated, the songs route calls the notification service, which creates a notification for the original sharer. I also noticed that the app uses a consistent pattern where routes handle request parsing and responses while services own the logic.

## Root Cause Analysis

### Issue 1: My listening streak keeps resetting
1. Issue number and title: Issue #1 — My listening streak keeps resetting
2. How you reproduced it: I triggered the streak update with a Saturday then Sunday sequence using the existing streak tests. The bug appeared when the second day was Sunday because the code treated it as a non-consecutive day.
3. How you found the root cause: I traced the update through routes/songs.py into services/streak_service.py and inspected the date comparison in update_listening_streak().
4. The root cause: The service used Python's weekday() logic and blocked Sunday from counting as the next day. That made a Sunday listen look like a reset instead of a continuation of the streak.
5. Your fix and side-effect check: I removed the Sunday-specific exception so any one-day gap increments the streak normally. I verified the related streak tests for consecutive days, same-day repeats, and skipped days still pass.

### Issue 2: Friends Listening Now shows people from yesterday
1. Issue number and title: Issue #2 — Friends Listening Now shows people from yesterday
2. How you reproduced it: I created a friend with one recent listen and one older listen, then called get_friends_listening_now(). The older event was still being included because the recency filter was too wide.
3. How you found the root cause: I followed the feed route into services/feed_service.py and inspected the recent-events cutoff.
4. The root cause: The service used a 24-hour threshold, so events from the previous day were still considered recent enough to appear in the feed.
5. Your fix and side-effect check: I reduced the threshold to 30 minutes to match the intended "listening now" behavior. I checked the feed logic and confirmed the recent-event test passes without changing the general activity-feed behavior.

### Issue 3: The same song keeps showing up twice in search
1. Issue number and title: Issue #3 — The same song keeps showing up twice in search
2. How you reproduced it: I searched for a song that had multiple tags and confirmed that the same result appeared multiple times in the service output.
3. How you found the root cause: I traced the search path from routes/songs.py into services/search_service.py and inspected the query that joined the tags table.
4. The root cause: The search query joined the tag association table, which multiplied each song once per tag and caused duplicates in the results list.
5. Your fix and side-effect check: I removed the join from the search query so each matching song is returned once while still allowing the search to work by title and artist. I verified that single-tag, multi-tag, and no-tag songs all return exactly one result.

### Issue 4: I got notified when a friend added my song to a playlist but not when they rated it
1. Issue number and title: Issue #4 — I got notified when a friend added my song to a playlist but not when they rated it
2. How you reproduced it: I rated a song that was shared by another user and checked whether a notification was created for the original sharer.
3. How you found the root cause: I traced the rating flow from routes/songs.py to services/notification_service.py and compared the rating logic with the existing playlist-add notification logic.
4. The root cause: The rating flow updated the score but never created a notification, even though the playlist-add path already had a notification pattern in place.
5. Your fix and side-effect check: I added a notification creation step after a successful rating when the rater is not the song owner. I verified the new notification behavior and confirmed the existing rating flow still works.

### Issue 5: The last song in a playlist never shows up
1. Issue number and title: Issue #5 — The last song in a playlist never shows up
2. How you reproduced it: I used the existing playlist tests, which showed that a playlist with five songs returned only four results.
3. How you found the root cause: I traced the playlist retrieval function in services/playlist_service.py and inspected the slice at the end of the result list.
4. The root cause: The service sliced off the final element from the query results, so the last song was dropped before the list was returned.
5. Your fix and side-effect check: I removed the slicing so all songs in the playlist are returned in their stored position order. I verified the full playlist and ordering tests pass.
