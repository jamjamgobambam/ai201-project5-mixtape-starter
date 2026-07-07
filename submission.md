## Issue #3 — The same song keeps showing up twice in search

### How I reproduced it
I tested the search endpoint using GET /songs/search?q=Anthem and also tried related terms like Borough and Crown. In my local run, the API returned one result, but the search code showed a condition that could create duplicate rows when a matching song has multiple tags.

### How I found the root cause
I started from the endpoint /songs/search?q=Anthem and searched the codebase for the search function. I found services/search_service.py and looked at search_songs(). The function queried Song but also joined the song_tags table even though the filter only checked Song.title and Song.artist.

### The root cause
The search query used an outer join to song_tags. Since one song can have multiple tags, the join can create multiple database rows for the same song. The search logic did not need this join because it was not filtering by tags. This created a duplicate-result risk for songs with multiple tags.

### Your fix and side-effect check
I removed the unnecessary outer join from the search query and kept the filter on Song.title and Song.artist. The song tags are still included through song.to_dict(), so the response still contains tags. I retested searches for Anthem and Borough to confirm the matching song still appears once.