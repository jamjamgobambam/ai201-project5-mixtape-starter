## Issue #1 — My listening streak keeps resetting

### How I reproduced it
I inspected the streak logic in `services/streak_service.py` and focused on the reported Saturday-to-Sunday behavior. The issue happens when a user listened the previous day and the current day is Sunday. In that case, `days_since_last` is 1, but `today.weekday()` is 6.

### How I found the root cause
I looked at the endpoint behavior described in the issue, then traced the streak update logic to `record_listening_event()` and `update_listening_streak()` in `services/streak_service.py`. The suspicious condition was the streak increment check: `days_since_last == 1 and today.weekday() != 6`.

### The root cause
Python's `date.weekday()` returns 6 for Sunday. The code only incremented the streak if the user listened yesterday and today was not Sunday. So when a user listened on Saturday and then again on Sunday, the condition failed and the code reset the streak to 1. This directly matches the user report that the streak reset on Sunday.

### Your fix and side-effect check
I removed the unnecessary Sunday check and changed the condition to only check `days_since_last == 1`. This matches the streak rule because any two consecutive calendar days should increase the streak. I checked that same-day listening still does not increase the streak and that gaps of more than one day still reset the streak to 1.




## Issue #3 — The same song keeps showing up twice in search

### How I reproduced it
I tested the search endpoint using GET /songs/search?q=Anthem and also tried related terms like Borough and Crown. In my local run, the API returned one result, but the search code showed a condition that could create duplicate rows when a matching song has multiple tags.

### How I found the root cause
I started from the endpoint /songs/search?q=Anthem and searched the codebase for the search function. I found services/search_service.py and looked at search_songs(). The function queried Song but also joined the song_tags table even though the filter only checked Song.title and Song.artist.

### The root cause
The search query used an outer join to song_tags. Since one song can have multiple tags, the join can create multiple database rows for the same song. The search logic did not need this join because it was not filtering by tags. This created a duplicate-result risk for songs with multiple tags.

### Your fix and side-effect check
I removed the unnecessary outer join from the search query and kept the filter on Song.title and Song.artist. The song tags are still included through song.to_dict(), so the response still contains tags. I retested searches for Anthem and Borough to confirm the matching song still appears once.