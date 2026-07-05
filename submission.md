# Codebase Map

**Main Files & Roles:**
* **`app.py`:** This file creates the application using Flask. It boots up the server, connects to the database, and registers the Blueprints. app.py imports the routes (like songs_bp) and attaches them to the app so the server knows where to send web traffic.
* **`models.py`:** This file defines the database schema using SQLAlchemy. It includes models like User and Song, as well as association tables like friendships and song_tags which are used to link many-to-many relationships together.
* **`routes/` (The Controllers):** These files (like songs.py and playlists.py) handle the web layer: incoming HTTP requests, JSON payloads, and HTTP status codes. Pattern: They do not contain business logic; they parse the request and immediately delegate the work to the services layer.
* **`services/` (The Brains):** These files (like search_service.py and streak_service.py) handle the core business logic. They do not interact directly with the web server; instead, they do the raw math, query and update the database, and format the data to return to the routes.

**Data Flow Trace: A user listens to a song**
1. The Request: When a user listens to a song, the POST /<song_id>/listen endpoint in routes/songs.py receives the incoming JSON request and extracts the user_id and song_id.
2. The Handoff: The route calls the record_listening_event() function located in services/streak_service.py.
3. The Business Logic: record_listening_event() creates a new listening event record in the database. It then calls update_listening_streak() to update the user's current streak and last listened date/time.
4. The Response: The listen function in routes/songs.py receives the event object back from the service and returns jsonify(event.to_dict()). The route sends back the data about the listening event itself (when it happened and what song it was) to the client.