"""
app.py — Mixtape

Flask application factory and database setup.
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()


def create_app(config=None):
    app = Flask(__name__)

    # Default configuration
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///mixtape.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

    if config:
        app.config.update(config)

    db.init_app(app)

    # Register blueprints
    from routes.songs import songs_bp
    from routes.playlists import playlists_bp
    from routes.users import users_bp
    from routes.feed import feed_bp

    app.register_blueprint(songs_bp, url_prefix="/songs")
    app.register_blueprint(playlists_bp, url_prefix="/playlists")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(feed_bp, url_prefix="/feed")

    register_index(app)

    with app.app_context():
        db.create_all()

    return app


def register_index(app):
    """A simple landing page that lists the available API endpoints.

    Mixtape is a JSON API with no route at '/', so a bare browser visit
    returns 404. This index links to the live GET endpoints, filling in real
    IDs from the seeded database when it is available so the links work
    out of the box.
    """
    from flask import render_template_string
    from markupsafe import escape

    template = """
    <!doctype html>
    <title>Mixtape API</title>
    <style>
      body { font: 15px/1.6 system-ui, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 16px; color: #1a1a1a; }
      h1 { margin-bottom: 4px; } .sub { color: #666; margin-top: 0; }
      code { background: #f2f2f2; padding: 1px 5px; border-radius: 4px; }
      li { margin: 6px 0; } .m { color: #888; font-size: 13px; }
      .post { color: #b8860b; }
    </style>
    <h1>🎵 Mixtape API</h1>
    <p class="sub">A JSON API — there's no homepage, so pick an endpoint below.</p>
    {% if seeded %}
      <p>Sample links use real seeded IDs:</p>
      <ul>
        <li><a href="/songs/search?q=Crown">GET /songs/search?q=Crown</a> <span class="m">— search songs</span></li>
        <li><a href="/playlists/{{ playlist_id }}/songs">GET /playlists/&lt;id&gt;/songs</a> <span class="m">— playlist songs (bug #5)</span></li>
        <li><a href="/feed/{{ user_id }}/listening-now">GET /feed/&lt;id&gt;/listening-now</a> <span class="m">— friends listening now (bug #2)</span></li>
        <li><a href="/feed/{{ user_id }}/activity">GET /feed/&lt;id&gt;/activity</a> <span class="m">— activity feed</span></li>
        <li><a href="/users/{{ user_id }}">GET /users/&lt;id&gt;</a> <span class="m">— user profile</span></li>
        <li><a href="/users/{{ user_id }}/streak">GET /users/&lt;id&gt;/streak</a> <span class="m">— listening streak (bug #1)</span></li>
        <li><a href="/users/{{ user_id }}/notifications">GET /users/&lt;id&gt;/notifications</a> <span class="m">— notifications (bug #4)</span></li>
      </ul>
      <p class="m">POST-only (use a client, not the browser):
        <code class="post">POST /songs/&lt;id&gt;/rate</code>,
        <code class="post">POST /songs/&lt;id&gt;/listen</code>,
        <code class="post">POST /playlists/&lt;id&gt;/songs</code></p>
    {% else %}
      <p>The database has no data yet. Run <code>python seed_data.py</code>, then reload this page.</p>
    {% endif %}
    """

    @app.route("/")
    def index():
        from models import User, Playlist
        user = db.session.query(User).first()
        playlist = db.session.query(Playlist).first()
        seeded = user is not None and playlist is not None
        return render_template_string(
            template,
            seeded=seeded,
            user_id=escape(user.id) if user else "",
            playlist_id=escape(playlist.id) if playlist else "",
        )


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
