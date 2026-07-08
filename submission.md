## Issue #1 — My listening streak keeps resetting

### How I reproduced it
I inspected the streak logic in `services/streak_service.py` and focused on the reported Saturday-to-Sunday behavior. The issue happens when a user listened the previous day and the current day is Sunday. In that case, `days_since_last` is 1, but `today.weekday()` is 6.

### How I found the root cause
I looked at the endpoint behavior described in the issue, then traced the streak update logic to `record_listening_event()` and `update_listening_streak()` in `services/streak_service.py`. The suspicious condition was the streak increment check: `days_since_last == 1 and today.weekday() != 6`.

### The root cause
Python's `date.weekday()` returns 6 for Sunday. The code only incremented the streak if the user listened yesterday and today was not Sunday. So when a user listened on Saturday and then again on Sunday, the condition failed and the code reset the streak to 1. This directly matches the user report that the streak reset on Sunday.

### Your fix and side-effect check
I removed the unnecessary Sunday check and changed the condition to only check `days_since_last == 1`. This matches the streak rule because any two consecutive calendar days should increase the streak. I checked that same-day listening still does not increase the streak and that gaps of more than one day still reset the streak to 1.


## Issue #2 — Friends Listening Now shows people from yesterday

### How I reproduced it
I inspected the Friends Listening Now logic in `services/feed_service.py`. The bug report said a friend who listened at 11pm yesterday still appeared around 9am today. That behavior matches a rolling 24-hour window because yesterday at 11pm is still within the last 24 hours.

### How I found the root cause
I traced the endpoint behavior to `get_friends_listening_now()` in `services/feed_service.py`. Inside that function, I found that the cutoff time was calculated using `datetime.now(timezone.utc) - RECENT_THRESHOLD`, where `RECENT_THRESHOLD` was set to 24 hours.

### The root cause
The feature was supposed to show friends who listened today, but the code was checking for friends who listened within the last 24 hours. A rolling 24-hour window allows yesterday evening’s listens to remain visible the next morning, which is exactly what the user reported.

### Your fix and side-effect check
I changed the cutoff from “now minus 24 hours” to the start of the current UTC calendar day. This means the feed only includes listening events from today. I also checked that the function still filters only the current user’s friends, still orders by most recent listen, and still deduplicates to show only one most recent song per friend.

## Issue #3 — The same song keeps showing up twice in search

### How I reproduced it
I tested the search endpoint using GET /songs/search?q=Anthem and also tried related terms like Borough and Crown. In my local run, the API returned one result, but the search code showed a condition that could create duplicate rows when a matching song has multiple tags.

### How I found the root cause
I started from the endpoint /songs/search?q=Anthem and searched the codebase for the search function. I found services/search_service.py and looked at search_songs(). The function queried Song but also joined the song_tags table even though the filter only checked Song.title and Song.artist.

### The root cause
The search query used an outer join to song_tags. Since one song can have multiple tags, the join can create multiple database rows for the same song. The search logic did not need this join because it was not filtering by tags. This created a duplicate-result risk for songs with multiple tags.

### Your fix and side-effect check
I removed the unnecessary outer join from the search query and kept the filter on Song.title and Song.artist. The song tags are still included through song.to_dict(), so the response still contains tags. I retested searches for Anthem and Borough to confirm the matching song still appears once.


## Issue #4 — I got notified when a friend added my song to a playlist but not when they rated it

### How I reproduced it
I inspected the notification behavior described in the issue. Playlist notifications worked when a friend added a shared song to a playlist, but rating a shared song only saved the rating and did not create a notification. I traced this through `services/notification_service.py`.

### How I found the root cause
I compared the working playlist notification path with the rating path in `services/notification_service.py`. The `add_to_playlist()` function called `create_notification()` after adding the song to a playlist. The `rate_song()` function saved or updated the rating, committed it, and returned the rating without calling `create_notification()`.

### The root cause
The rating logic was missing the notification creation step. The app saved the rating correctly, but there was no code that created a `song_rated` notification for the original sharer of the song. This is why the rating appeared on the song, but the owner never saw a notification.

### Your fix and side-effect check
I added a notification after the rating is committed. If the rater is not the original sharer, the app now creates a `song_rated` notification for the song owner. I also kept the self-notification guard so users do not receive notifications when rating their own songs. I checked that the existing rating save/update behavior still remains unchanged.

## Issue #5 — The last song in a playlist never shows up

### How I reproduced it
I inspected the playlist retrieval logic for `GET /playlists/<playlist_id>/songs`. The user report said the playlist count showed one more song than the endpoint returned, and the missing song was always the newest one. This matched the behavior of code that removes the final item from a list.

### How I found the root cause
I traced the playlist songs endpoint to `get_playlist_songs()` in `services/playlist_service.py`. The function queried songs in playlist order using `playlist_entries.c.position`, then returned `songs[:-1]`.

### The root cause
The code used Python slicing `songs[:-1]`, which means “all items except the last one.” Because songs are ordered by playlist position, the last item is the most recently added song. This caused the endpoint to always hide the newest song.

### Your fix and side-effect check
I changed the return statement from `songs[:-1]` to `songs`, so the function returns every song in the playlist. I checked that the ordering logic still stays the same because the query still orders by `playlist_entries.c.position`.