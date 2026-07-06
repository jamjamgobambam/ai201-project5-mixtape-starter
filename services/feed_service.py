"""
services/feed_service.py — Mixtape

Handles the "Friends Listening Now" feed and activity feed logic.
"""

from datetime import datetime, timedelta, timezone
from sqlalchemy import desc
from app import db
from models import User, Song, ListeningEvent


RECENT_THRESHOLD = timedelta(minutes=30)


def get_friends_listening_now(user_id: str) -> list[dict]:
    """
    Return a list of friends who have listened to something recently,
    along with the song they were listening to.

    Args:
        user_id: The ID of the current user.

    Returns:
        A list of dicts, each with 'friend', 'song', and 'listened_at' keys,
        ordered by most recent first.
    """
    user = db.session.get(User, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")

    cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD
    friend_ids = [f.id for f in user.friends]

    if not friend_ids:
        return []

    recent_events = (
        db.session.query(ListeningEvent)
        .filter(
            ListeningEvent.user_id.in_(friend_ids),
            ListeningEvent.listened_at >= cutoff,
        )
        .order_by(desc(ListeningEvent.listened_at))
        .all()
    )

    # Deduplicate: only show the most recent song per friend
    seen_friends = set()
    result = []
    for event in recent_events:
        if event.user_id not in seen_friends:
            seen_friends.add(event.user_id)
            friend = db.session.get(User, event.user_id)
            song = db.session.get(Song, event.song_id)
            result.append({
                "friend": friend.to_dict(),
                "song": song.to_dict(),
                "listened_at": event.listened_at.isoformat(),
            })

    return result


def get_activity_feed(user_id: str, limit: int = 20) -> list[dict]:
    """
    Return a general activity feed of recent listening events from all friends.

    Unlike get_friends_listening_now, this is not filtered by recency —
    it returns the most recent N events regardless of when they happened.

    Args:
        user_id: The ID of the current user.
        limit: Maximum number of events to return.

    Returns:
        A list of activity dicts ordered by most recent first.
    """
    user = db.session.get(User, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")

    friend_ids = [f.id for f in user.friends]
    if not friend_ids:
        return []

    events = (
        db.session.query(ListeningEvent)
        .filter(ListeningEvent.user_id.in_(friend_ids))
        .order_by(desc(ListeningEvent.listened_at))
        .limit(limit)
        .all()
    )

    result = []
    for event in events:
        friend = db.session.get(User, event.user_id)
        song = db.session.get(Song, event.song_id)
        result.append({
            "friend": friend.to_dict(),
            "song": song.to_dict(),
            "listened_at": event.listened_at.isoformat(),
        })

    return result


if __name__ == "__main__":
    import sys
    import os
    # Add root folder to sys.path to allow imports from app
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    from app import create_app, db
    from models import User
    
    print("=" * 60)
    print("DEMO: Feed Service Logic")
    print("=" * 60)
    
    app = create_app()
    with app.app_context():
        # Find the seed user "nova" who has friends
        nova = User.query.filter_by(username="nova").first()
        if not nova:
            print("Database not seeded. Please run 'python seed_data.py' first.")
            sys.exit(0)
            
        print(f"User: {nova.username}")
        print(f"Friends: {[f.username for f in nova.friends]}")
        print("-" * 60)
        
        print("Friends Listening Now (Last 30 mins):")
        listening_now = get_friends_listening_now(nova.id)
        if not listening_now:
            print("  No friends are listening now.")
        for item in listening_now:
            print(f"  - Friend: {item['friend']['username']}")
            print(f"    Song: '{item['song']['title']}' by {item['song']['artist']}")
            print(f"    Listened at: {item['listened_at']}")
            
        print("-" * 60)
        print("Activity Feed (recent events, unfiltered):")
        activity = get_activity_feed(nova.id, limit=5)
        for item in activity:
            print(f"  - Friend: {item['friend']['username']}")
            print(f"    Song: '{item['song']['title']}' by {item['song']['artist']}")
            print(f"    Listened at: {item['listened_at']}")
        print("=" * 60)
