# Mixtape

A social music app where friends share songs, build collaborative playlists, rate each other's picks, and track their listening stats. Mixtape is a small Flask + SQLAlchemy JSON API.

## Features

- **Song sharing & search** — share songs and search the catalog by title or artist.
- **Ratings** — rate a friend's song 1–5; the original sharer gets notified.
- **Collaborative playlists** — create playlists and add songs in an explicit order; the sharer is notified when their song is added.
- **Listening streaks** — every day you listen extends your streak; miss a day and it resets.
- **Friends Listening Now** — see which friends are listening right now (a rolling 30-minute window).
- **Activity feed** — a recency-ordered feed of your friends' latest listens.
- **Notifications** — in-app notifications for ratings and playlist adds, with read/unread state.

## Project structure

```
.
├── app.py                       # Flask application factory and DB setup
├── models.py                    # SQLAlchemy models and association tables
├── routes/
│   ├── songs.py                 # Search, song detail, rate, listen
│   ├── playlists.py             # Create playlist, list songs, add song
│   ├── users.py                 # Profile, streak, notifications
│   └── feed.py                  # Friends listening now, activity feed
├── services/
│   ├── streak_service.py        # Listening streak logic
│   ├── feed_service.py          # Listening-now / activity feed logic
│   ├── search_service.py        # Song search logic
│   ├── notification_service.py  # Notifications, ratings, playlist adds
│   └── playlist_service.py      # Playlist creation and retrieval
├── tests/                       # pytest suite
├── seed_data.py                 # Populates the DB with sample data
└── requirements.txt
```

Routes are a thin HTTP layer: they parse requests, call a service function, and shape the JSON response. All business logic lives in `services/`.

## Setup

Create and activate a virtual environment:

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows (Command Prompt)
.venv\Scripts\activate.bat

# Windows (Git Bash)
source .venv/Scripts/activate
```

Install dependencies and seed the database with sample data:

```bash
pip install -r requirements.txt
python seed_data.py
```

Run the app:

```bash
FLASK_APP=app:create_app flask run
```

The API is then available at `http://127.0.0.1:5000`.

> **macOS note:** If requests hang or return connection refused, use `http://127.0.0.1:5000` rather than `http://localhost:5000` — on macOS `localhost` can resolve to an IPv6 address Flask isn't listening on.

> Start the app with `flask run` (not `python app.py`) so the application factory is used and the database initializes correctly.

## API reference

### Songs
| Method | Path | Body / Query | Description |
|--------|------|--------------|-------------|
| `GET` | `/songs/search` | `?q=<query>` | Search songs by title or artist |
| `GET` | `/songs/<song_id>` | — | Get a single song |
| `POST` | `/songs/<song_id>/rate` | `{ "user_id", "score" }` | Rate a song 1–5 (notifies the sharer) |
| `POST` | `/songs/<song_id>/listen` | `{ "user_id" }` | Record a listen and update the streak |

### Playlists
| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/playlists/` | `{ "name", "created_by", "is_collaborative"? }` | Create a playlist |
| `GET` | `/playlists/<playlist_id>` | — | Get playlist metadata |
| `GET` | `/playlists/<playlist_id>/songs` | — | List songs in playlist order |
| `POST` | `/playlists/<playlist_id>/songs` | `{ "song_id", "added_by" }` | Add a song (notifies the sharer) |

### Users
| Method | Path | Body / Query | Description |
|--------|------|--------------|-------------|
| `GET` | `/users/<user_id>` | — | Get a user profile |
| `GET` | `/users/<user_id>/streak` | — | Get the user's listening streak |
| `GET` | `/users/<user_id>/notifications` | `?unread_only=true` | List notifications |
| `POST` | `/users/notifications/<notification_id>/read` | — | Mark a notification read |

### Feed
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/feed/<user_id>/listening-now` | Friends active in the last 30 minutes |
| `GET` | `/feed/<user_id>/activity` | Recent listening activity from friends |

## Data model

`models.py` defines the entities and three association tables:

- **User** — has a `listening_streak`, `last_listened_at`, and a symmetric many-to-many `friends` relationship.
- **Song** — shared by a user; has ratings, listening events, and tags.
- **Tag** — labels joined to songs via `song_tags`.
- **ListeningEvent** — one row per listen; drives streaks and the feed.
- **Rating** — a user's 1–5 score for a song (unique per user/song).
- **Playlist** — songs attached via `playlist_entries`, which carries `position`, `added_by`, and `added_at`, so playlist order is explicit.
- **Notification** — a message for a recipient, with a type, body, and read flag.

## Running tests

```bash
pytest tests/
```
