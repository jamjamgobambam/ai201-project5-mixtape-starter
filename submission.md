# Root Cause Analysis Entries — Draft

---

## Issue: Listening streak resets instead of incrementing on Sundays

**How I reproduced it**

Before touching any code, I wrote/ran a test that models two consecutive days of listening,
one of which lands on a Sunday:

```python
saturday = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)  # weekday() == 5
sunday = datetime(2024, 6, 16, 12, 0, 0, tzinfo=timezone.utc)    # weekday() == 6

update_listening_streak(u, saturday)
assert u.listening_streak == 1

update_listening_streak(u, sunday)
assert u.listening_streak == 2  # expected: increments, one day apart
```

Running this with `python3 -m pytest tests/test_streaks.py -k test_streak_increments_on_sunday`
failed with `assert 1 == 2` — the streak reset to 1 instead of incrementing, confirming the
reported behavior before I made any changes. The condition needed to trigger the bug is
specifically: two calls to `update_listening_streak` exactly one calendar day apart, where the
second call's date is a Sunday.

**How I found the root cause**

I opened `services/streak_service.py` and read `update_listening_streak` top to bottom to
understand the day-difference logic. Rather than guessing from the read alone, I added a
temporary debug print at the point where the day difference is computed, following the
execution-tracing approach of confirming inputs before assuming a cause:

```python
last_date = last_listened.date()
days_since_last = (today - last_date).days
print(f"[DEBUG] today={today} weekday={today.weekday()} last_date={last_date} days_since_last={days_since_last}")
```

Re-running the failing test with `pytest -s` (so the print isn't captured) showed:

```
[DEBUG] today=2024-06-16 weekday=6 last_date=2024-06-15 days_since_last=1
```

`days_since_last=1` confirmed the function was correctly identifying this as a consecutive-day
case. That meant the bug wasn't in the date-difference math — it had to be in the branching
condition that decides what to do with that value. That's what pointed me at the specific
`elif` line rather than the surrounding function in general.

**The root cause**

The increment branch was written as:

```python
elif days_since_last == 1 and today.weekday() != 6:
    user.listening_streak += 1
else:
    user.listening_streak = 1
```

Python's `datetime.weekday()` returns `6` for Sunday. The extra `and today.weekday() != 6`
condition means: only increment the streak if exactly one day has passed **and** today is not a
Sunday. When today *is* Sunday, `today.weekday() != 6` evaluates to `False`, so even a
legitimate one-day gap falls through to the `else` branch and resets the streak to 1 instead of
incrementing it. There is no reasonable rule in the feature spec that says Sundays should be
excluded from consecutive-day counting — this looks like a stray condition that doesn't belong
in the logic at all, rather than a mistaken date calculation.

**My fix and side-effect check**

I removed the weekday exclusion entirely, since the actual rule is just "exactly one day
passed since the last listen":

```python
elif days_since_last == 1:
    user.listening_streak += 1
else:
    user.listening_streak = 1
```

After the fix, I removed the temporary debug print and reran the full test file:

```bash
python3 -m pytest tests/test_streaks.py
```

All 5 tests passed, including the other streak tests covering same-day updates, multi-day gaps,
and first-time listens — confirming the fix didn't change behavior for any case other than the
Sunday boundary it was meant to address.

---

## Issue: Playlist is missing its last song

**How I reproduced it**

I ran the existing playlist test suite before making any changes:

```bash
python3 -m pytest tests/test_playlists.py
```

This failed two tests against a playlist seeded with 5 songs in positions 1–5:

- `test_playlist_returns_all_songs` — expected `len(songs) == 5`, got `4`
- `test_playlist_returns_songs_in_order` — expected `["Track 1", ..., "Track 5"]`, got only
  `["Track 1", "Track 2", "Track 3", "Track 4"]`

The condition that triggers the bug is simply: any playlist with at least one song — the last
song in position order is dropped every time, not just under specific edge-case data.

**How I found the root cause**

I opened `services/playlist_service.py` and read `get_playlist_songs`. The query itself looked
correct — it joins `Song` to the `playlist_entries` association table, filters by
`playlist_id`, and orders by `position` ascending, which matches the docstring's claim that it
"returns all songs in the playlist" in position order.

Rather than assume the query was the problem, I isolated the function using a Flask shell so I
could inspect the raw query result separately from the function's return statement:

```bash
FLASK_APP=app:create_app python -m flask shell
```

```python
from app import db
from models import Song, Playlist, playlist_entries
from sqlalchemy import asc

p = Playlist.query.first()

raw = (
    db.session.query(Song)
    .join(playlist_entries, Song.id == playlist_entries.c.song_id)
    .filter(playlist_entries.c.playlist_id == p.id)
    .order_by(asc(playlist_entries.c.position))
    .all()
)
print(len(raw), [s.title for s in raw])
```



The raw query returned all 5 songs in the correct order. That confirmed the database access and
join logic were fine, and told me the bug had to be somewhere between the query result and the
function's return value — which meant looking at the final line of the function specifically,
not the query building it.

**The root cause**

The function's return line was:

```python
return [song.to_dict() for song in songs[:-1]]
```

`songs[:-1]` slices off the last element of the already-correct, already-ordered list before
converting the remaining songs to dicts. Because the songs are ordered ascending by position,
the element being dropped is always whichever song is in the last position — which is why the
symptom was specifically "the last song is missing" rather than a random or duplicated song.

**My fix and side-effect check**

I removed the slice so the full ordered list is returned:

```python
return [song.to_dict() for song in songs]
```

I searched the codebase for other callers of `get_playlist_songs` to confirm nothing else
compensated for the previous off-by-one behavior (e.g. no caller was re-adding a song or
expecting a short list). Then I reran:

```bash
python3 -m pytest tests/test_playlists.py
```

All 3 tests passed, confirming playlists of all sizes now return every song in the correct
order without affecting playlist creation or metadata retrieval, which are handled by separate
functions in the same file.



Issue: Sharer isn't notified when their song is rated

How I reproduced it

There was no existing test file for notifications, so I reproduced this directly in a Flask
shell (FLASK_APP=app:create_app python -m flask shell):

pythonfrom services.notification_service import rate_song, get_notifications
from models import Song, User

song = Song.query.first()
rater = User.query.filter(User.id != song.shared_by).first()

before = get_notifications(song.shared_by)
print("before:", len(before))

rate_song(rater.id, song.id, 5)

after = get_notifications(song.shared_by)
print("after:", len(after))

Output:

before: 1
after: 1

rate_song returned a valid Rating object, confirming the rating itself was saved
successfully, but the sharer's notification count didn't change. This confirmed the bug: rating
a song you didn't share produces no notification for the person who shared it.

How I found the root cause

I opened services/notification_service.py and read through it end to end, since the hint
indicated this bug was architectural rather than a simple typo. I compared the two functions
that modify data associated with a shared song: add_to_playlist and rate_song.

add_to_playlist follows this pattern: perform the data change, commit, then check
if song.shared_by != added_by_user_id and call create_notification(...) if so.

rate_song performs its data change (insert or update the Rating row) and commits, but the
function ends immediately after return rating — there is no equivalent notification check or
create_notification call anywhere in the function. Once I placed both functions side by side,
the missing block was immediately obvious: rate_song was missing an entire step that its
sibling function has, not misapplying a condition.

The root cause

rate_song never calls create_notification. The module's docstring states notifications
should be generated "when friends interact with a user's shared songs," and add_to_playlist
correctly implements that for the playlist-add interaction. Rating a song is exactly this kind
of interaction, but the notification step for it was simply never written — the rating logic is
complete and correct on its own, it just never triggers the corresponding notification that the
app's design implies it should.

My fix and side-effect check

I added the same notification pattern used in add_to_playlist, guarded the same way against
self-notification:

pythondb.session.commit()

# Notify the person who originally shared the song (if it wasn't them who rated it)
if song.shared_by != user_id:
    create_notification(
        user_id=song.shared_by,
        notification_type="song_rated",
        body=f"{rater.username} rated your song '{song.title}' {score}/5.",
    )

return rating

I re-ran the same shell reproduction after the fix and confirmed the notification count went
from 1 to 2, with the new notification's body reading "darius rated your song 'Midnight Drive' 4/5." and type: 'song_rated'.

For side effects, I checked two related paths:


Self-rating: had the song's sharer rate their own song, and confirmed the notification
count did not change, since the song.shared_by != user_id guard correctly excludes this case
— matching the same guard already used in add_to_playlist.
Re-rating: called rate_song again for the same user/song pair with a different score,
and confirmed only one Rating row exists for that pair (the existing update branch is
unaffected by this change), and noted that re-rating currently fires an additional
notification each time, which matches the existing (unchanged) add_to_playlist behavior for
repeated adds and wasn't part of the reported bug.







## Codebase Map

Main files and their roles


app.py — Flask application factory (create_app). Initializes the Flask app and the
SQLAlchemy db instance that every model and service file imports.
models.py — Defines all 7 SQLAlchemy models: User, Tag, Song, ListeningEvent,
Rating, Playlist, Notification. Also defines 3 association tables for many-to-many
relationships: friendships (self-referential, symmetric user-to-user), song_tags
(song-to-tag), and playlist_entries (playlist-to-song, but with extra columns —
position, added_by, added_at — so it's really tracking how a song was added, not just
that it was added). Rating has a UniqueConstraint on (user_id, song_id), which is why
rating the same song twice updates the existing row instead of creating a duplicate.
seed_data.py — Populates the database with test users, songs, playlists, and
notifications for local development.
routes/ — 4 blueprint files: users.py, playlists.py, feed.py, songs.py. Each
route function parses the incoming request (JSON body or query params), calls a single
service function to do the actual work, and formats the response as JSON. Routes contain
essentially no business logic themselves.
services/ — 5 files: notification_service.py, streak_service.py,
playlist_service.py, search_service.py, feed_service.py. All business logic lives here.
Service functions take plain arguments (IDs, primitives) rather than Flask request objects,
which makes them callable directly from a Python/Flask shell for testing — this is how I
reproduced and verified the notification bug, since there was no route-level test for it.


Data flow — rating a song (traced while fixing the notification bug)


Client sends POST /<song_id>/rate with a JSON body containing user_id and score
(routes/songs.py, rate()).
The route validates that both fields are present, then calls
rate_song(user_id, song_id, int(score)) from services/notification_service.py.
rate_song validates the score is 1–5, looks up the Song and User (rater), checks for an
existing Rating row for that (user_id, song_id) pair, and either updates its score or
creates a new Rating. It commits the change.
After committing, rate_song checks whether the rater is different from song.shared_by
(the original sharer). If so, it calls create_notification(...), which inserts a new
Notification row for the sharer.
The route returns the serialized Rating (via rating.to_dict()) with a 201 status.


This flow originally had a gap at step 4 — rate_song performed steps 1–3 and returned without
ever calling create_notification, so the sharer never learned their song had been rated. This
was Issue #4, documented in the RCA entries below.

Patterns noticed


Strict routes/services separation: every route in songs.py does input parsing and
response formatting only; all actual logic (lookups, validation, commits, notification
triggers) lives in the corresponding service function. This made it straightforward to test
business logic directly in a Flask shell without going through HTTP.
UUID primary keys everywhere: every model uses a string UUID (generate_uuid()) as its
primary key rather than an auto-incrementing integer, generated client-side by SQLAlchemy's
default=.
Association tables carry metadata, not just links: playlist_entries isn't a plain join
table — it has position (used for ordering, relevant to the playlist bug I fixed),
added_by, and added_at. friendships and song_tags, by contrast, are plain link tables
with no extra columns.
Consistent to_dict() serialization: every model defines its own to_dict() method used
directly by routes to build JSON responses, rather than a shared/generic serializer.


## ai usage

I used Claude throughout this project, mainly for two things: setting up my environment when
flask run kept failing, and helping me navigate/trace the three bugs I fixed.

Environment setup: Early on, flask run couldn't find flask_sqlalchemy even after I'd
installed it, and python3 script.py couldn't import app. I pasted the exact tracebacks and
Claude helped me diagnose that my shell had both a conda base environment and my .venv
active at once (visible in my prompt as (.venv) (base)), which meant flask/python weren't
resolving to the venv's installed packages. The fix was running python -m flask run instead of
plain flask run, and using python -m pytest for test files instead of running them directly.
This wasn't code logic, just environment debugging, but it took real back-and-forth with actual
error output to resolve.

Where I had to verify things myself: In a couple of cases my first shell test after applying
the notification fix still showed no change (after: 1), and Claude correctly guessed this was
because I was reusing a Python shell session that had already imported the old version of the
module before my edit — restarting the shell fixed it. I verified this myself by actually
restarting and re-running, rather than just trusting the explanation. I also ran the self-rating
and re-rating side-effect checks myself based on Claude's suggestions, rather than assuming the
fix was safe without checking.