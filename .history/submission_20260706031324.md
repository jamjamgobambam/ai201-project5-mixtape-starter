AI Collaboration Summary
What I asked AI to explain, trace, or summarize:

Codebase Orientation: Before touching the code, I used copilot and claude AI to describe and help me map out the services/ layer, asking it to trace the data flow of a feature (like how a song gets added to a feed) to help me understand the architectural pattern.

Syntax and Library Quirks: I asked the AI to clarify specific Python and SQLAlchemy behaviors, such as confirming what integer datetime.weekday() returns for Sunday, and explaining how .outerjoin() handles one-to-many relationships in a database query.

What the AI helped me understand:

Jumping into an unfamiliar Python codebase is overwhelming, so the AI was incredibly helpful for translating complex execution flows into clear, conceptual analogies.

It helped me understand the "delegation pattern" of the app, clarifying that routes/ simply pass inputs while the actual business logic to trace lives entirely in services/.

It successfully pointed out structural differences between similar functions, such as identifying the missing notification logic in rate_song compared to add_to_playlist.

Where AI fell short:

Local Environment Troubleshooting: When I encountered a 404 Not Found error after booting the Flask server, the AI helped explain why it was happening (no root route defined in app.py), but I had to manually navigate to the /playlists endpoint in my browser to verify the server was actually running.

Validating Side-Effects: While the AI suggested adding .distinct() to fix the search duplicate bug, I could not blindly trust it. I had to manually run the search in my environment to verify that deduplicating the query didn't accidentally strip the nested tag data out of the final JSON response.

Reproducing the Bugs: I manually seed the database, trigger the HTTP requests, and verify the specific conditions (like testing a Sunday logic boundary) before implementing any suggested fixes.

graph TD
    subgraph Routes Layer "Routes (The Web Controllers - Handles inputs only)"
        R_Playlists[routes/playlists.py]
    end

    subgraph Service Layer "Services (Business Logic)"
        S_Notif[notification_service.py]
        S_Streak[streak_service.py]
        S_Feed[feed_service.py]
        S_Search[search_service.py]
        S_Playlist[playlist_service.py]
    end

    subgraph Database Layer "Models (The Save Files)"
        M_User[(User)]
        M_Song[(Song)]
        M_Playlist[(Playlist)]
        M_NotifDB[(Notification)]
        M_ListenEvent[(ListeningEvent)]
    end

    %% Data Flow Example: Adding to a playlist triggers a notification
    User[User adds song to Playlist] --> R_Playlists
    R_Playlists -->|Calls| S_Notif_add[notification_service.add_to_playlist]
    S_Notif_add -->|Updates DB| M_Playlist
    S_Notif_add -->|Checks if original sharer needs alert| S_Notif_create[notification_service.create_notification]
    S_Notif_create -->|Saves to DB| M_NotifDB

    %% General Architecture connections
    S_Streak --> M_ListenEvent
    S_Streak --> M_User
    S_Feed --> M_ListenEvent
    S_Search --> M_Song
    S_Playlist --> M_Playlist
    S_Playlist --> M_Song

Commits/All Commits.png

Issue 1: My listening streak keeps resetting

To confirm the bug, I simulated a user listening streak. I created a listening event for a user on a Saturday, which set their streak to 1. I then simulated advancing the system clock by 24 hours so the current day registered as Sunday, and triggered record_listening_event() again. Instead of incrementing to 2, the user's streak was incorrectly reset to 1.

Overview
I traced the logic top-down in services/streak_service.py. I started at the entry point, record_listening_event, which calculates the current time and passes it to update_listening_streak. Inside that function, I read through the if/elif/else block that handles the days_since_last variable. The moment of confidence came when I spotted a hardcoded day-of-the-week check (today.weekday() != 6) attached to the 1-day increment logic, which directly contradicted the stated business rule that streaks should increment on any consecutive calendar day.

Root Cause
The bug was caused by an extraneous condition in the streak increment logic. In Python's datetime module, weekday() returns 6 for Sunday. The update_listening_streak function required today.weekday() != 6 to be true in order to increment a streak. Therefore, whenever a user listened exactly one day after their previous session, but that current day was a Sunday, the condition evaluated to False. The code execution bypassed the increment step and fell into the else block, which incorrectly wiped the user's streak back to 1.

Fix & Check
The fix was to delete and today.weekday() != 6 from the elif statement, leaving only elif days_since_last == 1:. This allows the streak to increment based purely on the passage of a single calendar day. Afterward, I verified that skipping a day (days_since_last > 1) still correctly triggers the else block to reset the streak, and that normal consecutive weekday logins are entirely unaffected by the removed code. No other services rely on this specific line, making it a safe, targeted fix.


Issue 3: The same song keeps showing up twice in search

To confirm the bug, I looked at a song that had only one tag and searched for it; it returned a single result. I then found (or added) a song in the database that had multiple tags associated with it. When I searched for that specific song's title, the search returned duplicate entries of the exact same song. The number of duplicates matched the number of tags assigned to the song.

Overview
I opened services/search_service.py and examined the search_songs function. I read through the SQLAlchemy query being constructed. The moment of confidence came when I spotted the .outerjoin(song_tags, ...) line. Knowing how SQL joins operate, I realized that joining a one-to-many relationship (one song to many tags) multiplies the returned rows. Because the query lacked a deduplication step, SQLAlchemy was returning a separate Song object for every joined tag row.

Root Cause
The bug was caused by a database join multiplying the result set without a filter for uniqueness. When search_songs executes .outerjoin() on the song_tags association table, the underlying SQL engine generates a distinct row for every tag a song has. Because the query simply called .all() at the end, SQLAlchemy returned a Song instance for every one of those rows. Consequently, a song with three tags would be returned as three identical song dictionaries in the final list.

Fix & Check
The fix was to append the .distinct() method to the SQLAlchemy query chain immediately before the .all() execution. This forces the database to return only unique Song records, regardless of how many tag rows were evaluated during the join. Afterward, I verified that songs with multiple tags now only appear once in the search results. I also verified that the .distinct() call did not strip the tag data itself; the final JSON response still correctly lists all associated tags for the matched songs.


Issue 4: I got notified when a friend added my song to a playlist but not when they rated it

To confirm the bug, I simulated two distinct user interactions. First, User A shared a song. Next, User B added that song to a playlist; I checked User A's notifications and verified an alert was generated. Then, User B submitted a 5-star rating for that exact same song. I checked User A's notifications again and found no new alert, confirming that the rating action was entirely failing to trigger the notification system.

Overview
I opened services/notification_service.py to compare the two relevant functions: add_to_playlist and rate_song. I read the add_to_playlist function first to establish the expected baseline pattern, noting that it explicitly called the create_notification helper function at the end of its execution. I then traced the rate_song logic line-by-line. The moment of confidence came when I reached the end of the rate_song function and saw that it successfully committed the rating to the database but returned immediately without ever invoking create_notification.

Root Cause
The root cause was a missing architectural implementation, rather than a logic error. The rate_song function was never programmed to generate notifications. While the database transaction for saving the 1-5 score was working perfectly, the developer simply omitted the necessary create_notification() call that exists in other interactive features (like playlist additions). Because the code to send the alert didn't exist in that specific execution path, the system remained completely silent when a rating occurred.

Fix & Check
The fix was to implement the missing notification logic. I added an if block inside rate_song, immediately following the database commit, which checks if the rater is someone other than the original sharer (if song.shared_by != user_id:). If true, it calls create_notification() with a formatted string explaining the rating. Afterward, I verified that rating a friend's song now successfully generates a database entry in the Notifications table, and I ensured that users do not receive notifications when they rate their own shared songs, matching the intended boundary conditions.


Issue 5: The last song in a playlist never shows up

To confirm the bug, I created a new collaborative playlist and sequentially added three distinct songs (Song A, Song B, and Song C) to it. I then called the get_playlist_songs() function to view the playlist's contents. The function returned a list containing only Song A and Song B. The final item added (Song C) was missing from the output, confirming that the last entry is consistently dropped.

Overview
I opened services/playlist_service.py and navigated to the get_playlist_songs function. I traced the logic top-down, verifying that the SQLAlchemy query correctly fetched .all() records ordered by their position. Knowing the database was retrieving the full list, I checked how the data was being formatted for the return statement. The moment of confidence came when I read the final line: return [song.to_dict() for song in songs[:-1]]. I immediately recognized the Python slice syntax [:-1], which is explicitly designed to omit the final element of an array.

Root Cause
The bug was caused by an errant Python list slice on the return statement. The database query itself was functioning perfectly and retrieving every song in the playlist. However, right before returning the data, the code processed the results using songs[:-1]. In Python, a negative index in a slice counts backward from the end of the list, meaning [:-1] returns all elements up to, but not including, the very last one. This hardcoded slice intentionally discarded the final song object before it could be sent to the user.

Fix & Check
The fix was to remove the [:-1] slice from the return statement, changing it to return [song.to_dict() for song in songs]. This ensures the list comprehension iterates over every song retrieved from the database. Afterward, I verified that playlists with multiple items now display the final song. I also checked boundary conditions: I confirmed that a playlist with exactly one song now correctly returns that song (instead of an empty list), and that querying an empty playlist still safely returns an empty list without throwing an index error.