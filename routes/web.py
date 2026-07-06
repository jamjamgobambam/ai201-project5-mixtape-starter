"""
routes/web.py — Mixtape browsable web UI

A server-rendered, user-friendly frontend over the database. This is a thin
presentation layer: it reads through the same service functions the JSON API
uses and renders HTML templates.

Mounted at the root. It uses singular paths (/user, /song, /playlist) so it
never collides with the plural JSON API blueprints (/users, /songs, /playlists).
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from app import db
from models import User, Song, Playlist
from services.search_service import search_songs
from services.playlist_service import get_playlist_songs
from services.notification_service import get_notifications, rate_song, add_to_playlist
from services.streak_service import get_streak, record_listening_event
from services.feed_service import get_friends_listening_now, get_activity_feed

web_bp = Blueprint("web", __name__)


# --------------------------------------------------------------------------- #
# Pages (read)
# --------------------------------------------------------------------------- #

@web_bp.route("/")
def dashboard():
    users = db.session.query(User).order_by(User.username).all()
    playlists = db.session.query(Playlist).all()
    songs = db.session.query(Song).order_by(Song.shared_at.desc()).all()
    song_counts = {p.id: len(p.songs) for p in playlists}
    return render_template(
        "dashboard.html",
        users=users,
        playlists=playlists,
        songs=songs,
        song_counts=song_counts,
    )


@web_bp.route("/user/<user_id>")
def user_page(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    return render_template(
        "user.html",
        user=user,
        streak=get_streak(user_id),
        notifications=get_notifications(user_id),
        listening_now=get_friends_listening_now(user_id),
        activity=get_activity_feed(user_id, limit=10),
        friends=user.friends.all(),
        playlists=db.session.query(Playlist).filter_by(created_by=user_id).all(),
        all_songs=db.session.query(Song).order_by(Song.title).all(),
    )


@web_bp.route("/playlist/<playlist_id>")
def playlist_page(playlist_id):
    playlist = db.session.get(Playlist, playlist_id)
    if not playlist:
        abort(404)
    songs = get_playlist_songs(playlist_id)
    in_ids = {s["id"] for s in songs}
    available = [s for s in db.session.query(Song).order_by(Song.title).all()
                 if s.id not in in_ids]
    return render_template(
        "playlist.html",
        playlist=playlist,
        songs=songs,
        available=available,
        users=db.session.query(User).order_by(User.username).all(),
    )


@web_bp.route("/search")
def search_page():
    query = request.args.get("q", "").strip()
    results = search_songs(query) if query else []
    return render_template(
        "search.html",
        query=query,
        results=results,
        users=db.session.query(User).order_by(User.username).all(),
    )


# --------------------------------------------------------------------------- #
# Actions (write) — each wrapped so a failure flashes instead of 500-ing
# --------------------------------------------------------------------------- #

@web_bp.route("/user/<user_id>/listen", methods=["POST"])
def listen_action(user_id):
    song_id = request.form.get("song_id")
    try:
        record_listening_event(user_id, song_id)
        song = db.session.get(Song, song_id)
        flash(f"Recorded a listen to '{song.title}'. Streak updated.", "success")
    except Exception as e:  # noqa: BLE001 - surface any failure to the user
        db.session.rollback()
        flash(f"Could not record listen: {e}", "error")
    return redirect(url_for("web.user_page", user_id=user_id))


@web_bp.route("/song/<song_id>/rate", methods=["POST"])
def rate_action(song_id):
    user_id = request.form.get("user_id")
    score = request.form.get("score")
    back = request.form.get("next") or url_for("web.search_page", q=request.form.get("q", ""))
    try:
        rate_song(user_id, song_id, int(score))
        flash("Rating saved. The song's sharer was notified.", "success")
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        flash(f"Could not rate song: {e}", "error")
    return redirect(back)


@web_bp.route("/playlist/<playlist_id>/add", methods=["POST"])
def add_song_action(playlist_id):
    """Add a song to a playlist via the notification service, which records the
    entry and notifies the song's original sharer."""
    song_id = request.form.get("song_id")
    added_by = request.form.get("added_by")
    try:
        song = db.session.get(Song, song_id)
        add_to_playlist(playlist_id, song_id, added_by)
        flash(f"Added '{song.title}' to the playlist.", "success")
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        flash(f"Could not add song: {e}", "error")
    return redirect(url_for("web.playlist_page", playlist_id=playlist_id))
