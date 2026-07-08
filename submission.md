# Mixtape Codebase Map

## Overview

Mixtape app follows a layered structure:

- Routes handle HTTP requests, validate inputs, and format responses.
- Services contain the business logic for each feature.
- Models define the database structure using SQLAlchemy.
- The database stores users, songs, playlists, ratings, listening history, and notifications.

---

# Main Files and Responsibilities

## app.py

Responsible for creating the Flask application and configuring the database.

Main responsibilities:

- Creates the Flask app instance.
- Initializes SQLAlchemy.
- Registers route blueprints.
- Sets up the application environment.

---

## models.py

Defines the database models used throughout the application.

Main entities include:

- User:
  - Stores user information.
  - Tracks relationships to songs, playlists, and notifications.

- Song:
  - Represents songs shared in the app.
  - Stores song metadata and rating information.

- Playlist:
  - Represents collaborative playlists.

- PlaylistSong:
  - Join table connecting songs and playlists.
  - Stores playlist membership and ordering information.

- Notification:
  - Stores user notifications created by app events.

The models define how data is stored and how different parts of the application relate to each other.

---

# Routes

## routes/songs.py

Handles song-related API endpoints.

Responsibilities:

- Searching songs.
- Sharing songs.
- Rating songs.
- Calling song-related service functions.

Example:
A rating request enters through:

POST /songs/<song_id>/rate

The route processes the request and passes the business logic to the notification/song service layer.

---

## routes/playlists.py

Handles playlist endpoints.

Responsibilities:

- Creating playlists.
- Adding songs.
- Retrieving playlist contents.

Playlist operations delegate logic to playlist services.

---

## routes/users.py

Handles user-related functionality.

Responsibilities:

- User profiles.
- Listening streak requests.
- Notification retrieval.

---

## routes/feed.py

Handles friend activity feeds.

Responsibilities:

- Returning "Friends Listening Now".
- Loading listening activity from services.

---

# Services

## services/streak_service.py

Contains listening streak calculations.

Responsibilities:

- Determines consecutive listening days.
- Calculates the current streak.
- Handles date comparisons.

Related issue:
Issue #1 — listening streak resetting.

---

## services/feed_service.py

Contains friend activity feed logic.

Responsibilities:

- Finds friends' recent listening activity.
- Determines which listeners appear in "Friends Listening Now".

Related issue:
Issue #2 — yesterday's activity appearing in today's feed.

---

## services/search_service.py

Contains song search logic.

Responsibilities:

- Searching songs.
- Formatting search results.

Related issue:
Issue #3 — duplicate search results.

---

## services/notification_service.py

Handles notification creation and retrieval.

Responsibilities:

- Creating notifications for user actions.
- Fetching notifications for users.

Related issue:
Issue #4 — missing rating notifications.

---

## services/playlist_service.py

Handles playlist retrieval logic.

Responsibilities:

- Fetching playlist songs.
- Managing playlist ordering/display.

Related issue:
Issue #5 — newest playlist song missing.

---

# One Data Flow Walkthrough

## User rates a song and creates a notification

1. User sends:

POST /songs/<song_id>/rate

2. Request enters:

routes/songs.py

3. Route calls the relevant service function.

4. Rating information is saved to the Song model.

5. Notification service creates a Notification record for the song owner.

6. User retrieves notifications through:

GET /users/<my_id>/notifications

The route layer handles requests and responses, while the service layer handles application logic.

---

# Patterns Observed

## Service-based architecture

The application separates responsibilities:

- Routes = API handling.
- Services = business rules.
- Models = database structure.

Most routes delegate immediately to service functions rather than containing business logic themselves.

## Shared database models

Features are connected through common models:

- Songs connect sharing, ratings, and notifications.
- Playlists use a join table to connect users and songs.
- User activity powers streaks and feeds.

## Bugs are likely localized

Since each issue maps to a specific service file, we should start debugging by tracing the route backwards into its service function instead of changing routes or models immediately.
