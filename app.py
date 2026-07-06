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

    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, use_reloader=False)
