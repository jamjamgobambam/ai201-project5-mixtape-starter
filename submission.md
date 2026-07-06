# Mixtape Bug Hunt Submission

## AI Usage

I used AI tools mainly as a coding partner while navigating and debugging the codebase, not just to generate code. At the beginning, I used AI help to summarize the files I had already opened, especially the route files and service files, so I could build a clearer map of how requests move through the app.

For debugging, I used AI assistance after I had already found the suspicious code path myself. For the streak bug, I traced the listen route into `streak_service.py` and then used AI help to reason through the `weekday()` condition. For the notification bug, I compared the rating flow with the playlist-add flow and used AI help to explain the structural difference between them. For the playlist bug, I had already found `songs[:-1]`, and AI helped confirm that this slice means "everything except the last item."

I did not rely on the AI explanation by itself. I verified each diagnosis by reading the code, reproducing the bug, changing the smallest piece of logic, and rerunning the tests. One place where I had to be careful was Issue #3: the issue list said search could duplicate songs, but the local tests and API request returned one result, so I did not claim that bug as one of my three fixed issues.

## Milestone 4: Final Review

I checked the commit history on the `bugfix/mixtape` branch with `git log --oneline`. The three bug fixes are in separate commits and each uses a `fix:` message:

```text
2bffbce fix: return all songs in playlist results
e92475f fix: notify song sharers when friends rate songs
30b451a fix: allow streaks to increment on Sundays
```

I also reviewed the root cause analysis entries for the three fixed bugs. Each entry includes how I reproduced the bug, how I found the root cause, the root cause itself, the fix, and the side-effect checks I ran afterward.

Final verification:

```text
15 passed
```

Screenshot evidence:

The final terminal screenshot shows `git log --oneline` on the `bugfix/mixtape` branch with these commits:

```text
9bdbfcd docs: add final review and AI usage
2bffbce fix: return all songs in playlist results
e92475f fix: notify song sharers when friends rate songs
30b451a fix: allow streaks to increment on Sundays
```

The same screenshot also shows the full test command:

```powershell
.venv\Scripts\python.exe -m pytest tests
```

and the final result:

```text
15 passed in 1.61s
```

## Milestone 1: Codebase Map

### Setup

I worked on the `bugfix/mixtape` branch. The repo already had a `.venv`, so I used that instead of creating a new one. I checked the dependencies with:

```powershell
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
```

Everything was already installed. Then I seeded the database:

```powershell
.venv\Scripts\python.exe seed_data.py
```

The seed script created 5 users, 13 songs, 3 playlists, and 10 tags. I also started the Flask app with the app factory command, not `python app.py`, and confirmed that the app responded at `http://127.0.0.1:5000` by calling the song search endpoint.

Before changing any code, I ran the tests:

```powershell
.venv\Scripts\python.exe -m pytest tests
```

The starting result was 10 passing tests and 3 failing tests. The failures were useful because they confirmed the Sunday streak bug and the playlist missing-last-song bug.

### How I read the codebase

I started with `README.md` because it explains the app structure and lists the five known bugs. After that, I read the files in the order that made the app easiest to understand:

1. `app.py`, to see how the Flask app is created and how the routes are registered.
2. `models.py`, to understand the database tables and relationships.
3. `seed_data.py`, to understand what test data exists and which bugs the data is meant to expose.
4. The files in `routes/`, to see what each endpoint does.
5. The files in `services/`, because the README says the bugs are in the service layer.
6. The tests, to see which bugs already had reproduction cases.

The main pattern I noticed is that routes are thin and services do the real work. A route usually reads request data, calls a service function, and returns JSON. The service function handles the business logic and usually commits database changes.

### Main files

`app.py` is the Flask app factory. It creates the app, sets the database URI, initializes SQLAlchemy, registers the blueprints, and creates the database tables.

`models.py` defines the database models. The important models are `User`, `Song`, `Tag`, `ListeningEvent`, `Rating`, `Playlist`, and `Notification`. It also defines association tables for friendships, song tags, and playlist entries. The playlist entries table matters because it has a `position` column, so playlist song order is stored directly in the database.

`seed_data.py` resets the database and creates sample users, friendships, songs, tags, playlists, listening events, and one example notification. This file helped a lot because its comments explain what the seed data is supposed to represent.

`routes/songs.py` handles song search, song details, rating a song, and recording a listen.

`routes/playlists.py` handles creating playlists, getting playlist details, getting playlist songs, and adding songs to playlists.

`routes/users.py` handles user details, streak lookup, notification lookup, and marking notifications as read.

`routes/feed.py` handles the friends listening now feed and the general activity feed.

`services/streak_service.py` contains the listening streak logic. It creates listening events and updates the user's current streak.

`services/feed_service.py` builds the friends listening now feed and the activity feed from listening events.

`services/search_service.py` searches songs by title or artist.

`services/notification_service.py` creates notifications, adds songs to playlists, saves ratings, gets notifications, and marks notifications as read.

`services/playlist_service.py` creates playlists and returns playlist metadata or ordered playlist songs.

### Data model

A `User` has a username, email, listening streak, last listened time, friends, ratings, listening events, notifications, playlists, and shared songs.

A `Song` belongs to the user who shared it. Songs can also have tags, ratings, and listening events.

A `ListeningEvent` connects a user, a song, and the time the song was listened to. This model is used by both the streak feature and the feed feature.

A `Rating` stores one user's score for one song. The database has a uniqueness rule so the same user cannot create multiple separate ratings for the same song.

A `Playlist` is connected to songs through `playlist_entries`. That join table also stores the song position, who added the song, and when it was added.

A `Notification` belongs to a user and stores the notification type, message body, created time, and whether it has been read.

### Feature flow: rating a song

When a user rates a song, the request goes to `POST /songs/<song_id>/rate` in `routes/songs.py`. The route checks for `user_id` and `score`, then calls `notification_service.rate_song`.

Inside `rate_song`, the service checks that the score is between 1 and 5. It loads the song and the user, checks whether the user has already rated that song, and either updates the old rating or creates a new one. Then it commits and returns the rating.

The important thing I noticed is that this flow saves the rating, but it does not notify the person who originally shared the song. That is different from the playlist flow, where the original sharer does get notified.

### Feature flow: adding a song to a playlist

When a user adds a song to a playlist, the request goes to `POST /playlists/<playlist_id>/songs` in `routes/playlists.py`. The route sends the work to `notification_service.add_to_playlist`.

That service loads the song, the user adding it, and the playlist. If the song is not already in the playlist, it adds it and commits. Then, if the person adding the song is not the original sharer, it creates a notification for the original sharer.

This gave me the pattern that the rating feature probably should follow too.

### Patterns I noticed

- Routes mostly handle input and output.
- Services hold the business logic.
- Services raise `ValueError` when something is missing or invalid.
- Routes convert those `ValueError`s into JSON error responses.
- Database changes are usually committed inside the service function.
- The tests focus on service functions more than full HTTP requests.
- The bugs are small service-layer mistakes, not large design problems.

## Five Issue Scan

I read through all five issues before choosing which ones to reproduce first.

| Issue | Title | Affected service | My status |
| --- | --- | --- | --- |
| #1 | My listening streak keeps resetting | `streak_service.py` | Reproduced and chosen |
| #2 | Friends Listening Now shows people from yesterday | `feed_service.py` | Reproduced as a backup/extra |
| #3 | The same song keeps showing up twice in search | `search_service.py` | Read, but not chosen |
| #4 | I got notified when a friend added my song to a playlist but not when they rated it | `notification_service.py` | Reproduced and chosen |
| #5 | The last song in a playlist never shows up | `playlist_service.py` | Reproduced and chosen |

The three I chose first are #1, #4, and #5. I also reproduced #2, so that could be a good extra fix. I did not choose #3 because the search tests passed and my API search returned only one result, so I could not honestly say I reproduced that bug yet.

## Milestone 2: Bug Reproduction Notes

### Issue #1: listening streak resets on Sunday

I reproduced this with the test suite. The failing test was:

```text
tests/test_streaks.py::test_streak_increments_on_sunday
```

The test listens on Saturday, June 15, 2024, then listens again on Sunday, June 16, 2024. Since those are consecutive days, the streak should go from 1 to 2.

What actually happened was that the streak stayed at 1.

The likely cause is in `services/streak_service.py`. The code only increments the streak when `days_since_last == 1 and today.weekday() != 6`. Since Sunday has `weekday() == 6`, the code treats a valid Saturday-to-Sunday streak as if it should reset.

### Issue #4: rating a friend's song does not create a notification

I reproduced this using the seeded data and the running Flask app.

In the seed data, Simone shared `Crown Heights Anthem`. I had Nova rate that song with this request:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/songs/bad11138-2ef0-41af-99db-d1f0ce4f2cef/rate' -Method Post -ContentType 'application/json' -Body '{"user_id":"b4566de0-a086-4b71-802c-a3c5a505ef50","score":5}'
```

The request worked and returned a rating with score 5, so the rating itself was saved.

Then I checked Simone's notifications:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/users/482fef51-4e9a-42a5-957a-e7f80013c19f/notifications'
```

The response still had `count: 0`.

Expected behavior: Simone should get a notification because someone rated a song she shared.

Actual behavior: the rating is saved, but no notification is created.

The likely cause is that `notification_service.rate_song` commits the rating and returns it, but never calls `create_notification`. The playlist add feature already has this notification pattern, so the rating feature is missing a similar step.

### Issue #5: the last song in a playlist is missing

I reproduced this in two ways.

First, the test suite failed on:

```text
tests/test_playlists.py::test_playlist_returns_all_songs
tests/test_playlists.py::test_playlist_returns_songs_in_order
```

The test playlist has 5 songs, but `get_playlist_songs` only returned 4. The titles stopped at `Track 4`, so `Track 5` was missing.

I also checked it through the Flask app using seeded data:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/playlists/d4a44990-6ea9-46e1-bd47-2cea2906a3f4/songs'
```

The seeded `Late Night Vibes` playlist has 7 songs, but the response count was 6.

The likely cause is in `services/playlist_service.py`. The query gets the songs in the right order, but the return line uses `songs[:-1]`, which removes the final song every time.

## Extra Reproduction: Issue #2

I also reproduced the friends listening now issue.

After seeding the database, I checked the listening now results for the seeded users. Some users saw Nova listening to `Midnight Drive` from about two hours earlier. The seed comments say only events from the last 30 minutes should count as recent, but the service is allowing much older events.

Expected behavior: friends listening now should only show very recent listening activity.

Actual behavior: it includes events from hours earlier.

The likely cause is that `services/feed_service.py` sets:

```python
RECENT_THRESHOLD = timedelta(hours=24)
```

That means anything from the last 24 hours can appear in listening now, which is too broad for this feature.

## Milestone 3: Root Cause Analysis and Fixes

### Issue #1: My listening streak keeps resetting

How I reproduced it:

I reproduced this before editing code by running the test suite. The specific failing test was `tests/test_streaks.py::test_streak_increments_on_sunday`. It created a user, recorded a listen on Saturday, June 15, 2024, then recorded another listen on Sunday, June 16, 2024. Since those dates are one day apart, the streak should have become 2. Instead, it stayed at 1.

How I found the root cause:

I traced the feature from `routes/songs.py`, where `POST /songs/<song_id>/listen` calls `record_listening_event`, into `services/streak_service.py`. From there, `record_listening_event` creates the `ListeningEvent` and calls `update_listening_streak`. That made `update_listening_streak` the exact place to inspect. The moment that made the cause clear was the condition `days_since_last == 1 and today.weekday() != 6`. The test was failing only on Sunday, and Python's `weekday()` returns `6` for Sunday.

The root cause:

The streak logic was treating Sunday as an exception even when the previous listen was exactly one day earlier. The code correctly calculated `days_since_last`, but then added an extra condition that blocked streak increments on Sundays. Because of that, a normal Saturday-to-Sunday streak fell through to the reset branch.

My fix and side-effect check:

I changed the condition from `elif days_since_last == 1 and today.weekday() != 6:` to `elif days_since_last == 1:`. That keeps the intended rule simple: if the last listen was yesterday, increment the streak, no matter which weekday today is. I checked the related boundary behavior with the streak tests: new users still start at 1, same-day listens still do not double-count, skipped days still reset, and Saturday-to-Sunday now increments correctly.

### Issue #4: I got notified when a friend added my song to a playlist but not when they rated it

How I reproduced it:

I reproduced this through the running Flask app with seeded data. Simone shared `Crown Heights Anthem`, and Nova rated it with a score of 5. The rating endpoint returned a successful rating response, but when I checked Simone's notifications afterward, the response still had `count: 0`.

How I found the root cause:

I traced the rating request from `routes/songs.py`. The route for `POST /songs/<song_id>/rate` calls `notification_service.rate_song`, so I compared that function with `notification_service.add_to_playlist`. The playlist function already had the behavior I expected: after adding a song, it checks whether the adder is different from the original sharer and then calls `create_notification`. The rating function did the validation and saved the rating, but stopped after `db.session.commit()`. That comparison made the missing step clear.

The root cause:

The rating service was only saving the rating. It never created a `Notification` for the user who originally shared the song. So the database had the new `Rating` row, but there was no matching `song_rated` notification for the song owner.

My fix and side-effect check:

I added a notification step to `rate_song` after the rating is committed. If the rater is not the same user who shared the song, the service now creates a `song_rated` notification for the original sharer. I also added tests in `tests/test_notifications.py` for both sides of the behavior: a friend rating someone else's song creates one notification, and rating your own song does not notify yourself.

### Issue #5: The last song in a playlist never shows up

How I reproduced it:

I reproduced this with the playlist tests before editing code. The failing tests were `tests/test_playlists.py::test_playlist_returns_all_songs` and `tests/test_playlists.py::test_playlist_returns_songs_in_order`. The test playlist had 5 songs, but the service returned only 4, ending at `Track 4` instead of `Track 5`. I also reproduced it through the Flask app with seeded data: the `Late Night Vibes` playlist had 7 entries, but the endpoint returned `count: 6`.

How I found the root cause:

I traced the playlist endpoint from `routes/playlists.py`. `GET /playlists/<playlist_id>/songs` calls `playlist_service.get_playlist_songs`, so I inspected that function. The query joined `Song` to `playlist_entries`, filtered by playlist ID, and ordered by `position`, which all matched the expected behavior. The specific problem was the final return line: it used `songs[:-1]`. Since the query result itself was already correct, that slice was the exact place where the last song was being removed.

The root cause:

The service was intentionally or accidentally slicing off the final item before serializing the songs. In Python, `songs[:-1]` means "all items except the last one." So every non-empty playlist lost its final song, even though the database query found it.

My fix and side-effect check:

I changed the return line to serialize `songs` instead of `songs[:-1]`. This keeps all songs returned by the ordered query. I checked related behavior with the playlist tests: a playlist with 5 songs now returns all 5, the order is still `Track 1` through `Track 5`, and an empty playlist still returns an empty list.

## Conclusion

The Mixtape app is organized in a clear way: Flask routes handle requests, service files contain the actual logic, and SQLAlchemy models define the data. Once I understood that structure, the bugs were easier to trace because each issue pointed to one service file.

The three bugs I chose were all service-layer problems. The streak bug came from a bad Sunday condition, the notification bug came from a missing notification call after rating, and the playlist bug came from slicing off the last song before returning results. I fixed each one with a small targeted change, documented the root cause, and reran the tests afterward. The final full test run passed with 15 tests passing.
