## Codebase map


- main files
# models.py 
Defines the different databases for User, Tag, Song, ListeningEvent, Rating, Playlist, Notification

    Data flow to add a song to a playlist : 
    
    user pulls up playlist "POST /playlists/<playlist_id>/songs"

    then routes/playlists.py calls add_song(playlist_id)

    then services/notification_service.py calls add_to_playlist(playlist_id, song_id, added_by)

    Adding a song to playlist calls two functions which in the end adds a song to a playlist and creates a notification to alert the original sharer

# seed_data.py
Creates a testing environment by creating multiple users with different friendships, some have music currently listening and test playlist and test streaks.

# app.py
Starts up the flask app and registers blueprints for songs, playlists, users and feed

- routes

# songs.py
four functions/gatways
    search() -> GET /search?q -> search_songs(q) 
        - Searches for songs, 400 if missing
    
    get_song_detail(song_id) -> GET /<song_id> -> get_song(id) 
        - gets song details, returns 404 if not found

    rate(song_id) -> POST /<song_id>/rate -> rate_song(user_id, song_id, score)
        - takes in a user_id and a score to run function

    listen(song_id) -> POST /<song_id>/listen -> record_listening_event(user_id, song_id) 
        - Saves listen to a song and updates streak if applicable to song
# feed.py
two functions/gateways
    listening_now(user_id) -> GET /<user_id>/listening-now -> get_friends_listening_now(user_id)
        - friends who listened in the last 24h, 404 if user missing

    activity(user_id) -> GET /<user_id>/activity -> get_activity_feed(user_id)
        - the 20 most recent friend listening events

# playlists.py
four functions
    create() -> POST / -> create_playlist(name, created_by, is_collaborative)
        - makes a playlist, 400 if name or created_by missing

    get_detail(playlist_id) -> GET /<playlist_id> -> get_playlist(id)
        - playlist metadata only

    get_songs(playlist_id) -> GET /<playlist_id>/songs -> get_playlist_songs(id)
        - all songs in the playlist

    add_song(playlist_id) -> POST /<playlist_id>/songs -> add_to_playlist(playlist_id, song_id, added_by)
        - adds a song and notifies the original sharer

# users.py
four functions
    get_user(user_id) -> GET /<user_id>
        - returns user info, 404 if missing (reads the DB directly)

    streak(user_id) -> GET /<user_id>/streak -> get_streak(user_id)
        - current listening streak

    notifications(user_id) -> GET /<user_id>/notifications -> get_notifications(user_id, unread_only)
        - lists notifications, reads ?unread_only=true

    read_notification(notification_id) -> POST /notifications/<notification_id>/read -> mark_as_read(id)
        - marks one notification read

- Services

# feed_service.py
two functions
    get_friends_listening_now(user_id) - shows friends who listen to music in the last 24hr (newest first with no dupes)

    get_activity_feed(user_id, limit = 20) - shows the 20 most recent friend listening events

# notification_service.py
five functions
    create_notification(user_id, notification_type, body) - makes a notitfication

    add_to_playlist(playlist_id, song_id, added_by_user_id) - adds a song to playlist and sends a notification to person who originally shared it

    rate_song(user_id, song_id, score) - make a rating from 1-5 on a song

    get_notifications(user_id, unread_only=False) - get all of a users notifications, newest to olders

    mark_as_read(notification_id) - just to mark a read notification
# playlist_service.py
four functions
    create_playlist(name, created_by_user_id, is_collaborative=True) - makes a new playlist

    get_playlist_songs(playlist_id) - returns all the songs in a playlist in order

    get_playlist(playlist_id) - metadata for playlist, does not return songs

    get_user_playlists(user_id) - returns all playlist created by one user
# search_service.py
two functions
    search_songs(query) - used to find title/artisit

    get_song(song_id) - returns song from matching id

# streak_service.py
three functions
    record_listening_event(user_id, song_id) - to log a song listen and to add to the streak

    update_listening_streak(user, now) - streak logic which always begins at 1 and adds 1 everyday, while missing one day resets it

    get_streak(user_id) - returns the streak count of a specific user



## pattern

A pattern i noticed is how every step validates if a song or user is present in the database session when doing any action



## Bug Reporduction

- Issue #2 - Friends Listening Now Shows People from yesterday

    python -m flask --app "app:create_app" run --port 5055 --no-debugger --no-reload

    discover a user id (darius shares "Block Party")
curl -s "http://localhost:5055/songs/search?q=Block%20Party"

    read his "listening now" feed
curl -s "http://localhost:5055/feed/<darius_id>/listening-now"

    Result = 
    count = 2
    simone   Still Waters      listened   0.26 hours ago   <- genuinely "now"
    nova     Midnight Drive    listened   2.01 hours ago   <- stale

    Add a "ghost" who listened to music 23 hour ago. The seed data only had 2 hours as maximum amount in the past, A script was used to create the new user

    GET /feed/<nova>/listening-now
count = 4
  darius   Midnight Drive     0.19h ago
  simone   Still Waters       0.27h ago
  kenji    First Light        0.35h ago
  ghost    Golden Hour       23.00h ago   <-- YESTERDAY


    The user_id's who have music in "Listening now" shows the bug, that music listened to in the past 24 hours count as "Currently Listening", the code has a comment for 30 minutes to count as currently listening


- Issue #4 - I get notified when a friend added my song to a playlist but not when they rated it

    darius rates nova's song "Midnight Drive" 5 stars

    BEFORE: nova's notifications
curl -s "http://localhost:5055/users/<nova>/notifications"
  count = 1
    - song_added_to_playlist | darius added your song 'Midnight Drive' to the playlist 'Late Night Vibes'

    POST the rating
curl -s -X POST "http://localhost:5055/songs/<song>/rate" \
  -H "Content-Type: application/json" -d '{"user_id":"<darius>","score":5}'
  -> HTTP 201    (rating saved successfully)

    AFTER: nova's notifications — unchanged
curl -s "http://localhost:5055/users/<nova>/notifications"
  count = 1
    - song_added_to_playlist | darius added your song 'Midnight Drive' to the playlist 'Late Night Vibes'

    When a user adds a song that was shared by someone else, the function to send the notification gets called. But when a user rates the song, the same function isnt called to send the notification to the original sharer


- Issue #5 - The last song in a playlist never shows up

    # reproduce bug
    Bug: get_playlist_songs drops the last song (returns 4 of 5)
    pytest tests/test_playlists.py::test_playlist_returns_all_songs -v

    FAILED tests/test_playlists.py::test_playlist_returns_all_songs - AssertionError: assert 4 == 5

    Playlist has 5 songs saved to it, running a Pytest returned that the same playlist contained 5 items but only returned 4, easiest to test because of pytest, So all the songs are in the list, returning the songs causes the last missing song


    # How I found the route clause

    Using a pytest function made it apparent that all songs were saving correctly to the playlist in playlist_service.py but wasnt correctly returning. Any song with more than 1 song in a playlist is the data condition to find this bug


    # The Root Cause
    The return part of the function slices the list with [:-1]. This causes the last song not to be returned, changing to song in songs should accurately iterate through the whole list

    # Fix and side effect check

    return [song.to_dict() for song in songs[:-1]]

    ->

    return [song.to_dict() for song in songs]

    

    Side effect check - I checked to see if returning a playlist with one song will accurately return the song or an empty list, the function still returned the appropiate amount of songs

    pytest tests/test_playlists.py::test_single_song_playlist_returns_the_song -v
