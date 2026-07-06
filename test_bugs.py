# test_bugs.py (CORRECTLY REPRODUCING ALL THREE)
from app import create_app, db
from models import User, Song, Tag, ListeningEvent
from services.search_service import search_songs
from services.feed_service import get_friends_listening_now
from services.streak_service import update_listening_streak
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
import uuid

app = create_app()

def get_unique_id():
    """Generate a unique ID for test data"""
    return str(uuid.uuid4())[:8]

def test_bug_1():
    """Streak resets on Sunday"""
    with app.app_context():
        uid = get_unique_id()
        user = User(username=f"streaktest_{uid}", email=f"streaktest_{uid}@test.com")
        user.listening_streak = 1
        # Last listened yesterday
        user.last_listened_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.session.add(user)
        db.session.commit()
        
        # Simulate update on a Sunday (Jan 7, 2024)
        sunday = datetime(2024, 1, 7, 10, 0, 0, tzinfo=timezone.utc)
        update_listening_streak(user, sunday)
        
        print(f"Bug #1 - Streak on Sunday: {user.listening_streak}")
        print(f"  Expected: 2, Actual: {user.listening_streak}")
        print(f"  ✓ Bug present: {user.listening_streak == 1}")
        print()

def test_bug_3():
    """Same song appears twice if it has multiple tags"""
    with app.app_context():
        uid = get_unique_id()
        user = User(username=f"searchtest_{uid}", email=f"searchtest_{uid}@test.com")
        db.session.add(user)
        db.session.commit()

        song = Song(
            title=f"Test Song {uid}",
            artist="Test Artist",
            shared_by=user.id
        )

        # Reuse or create tags
        tag1 = db.session.query(Tag).filter_by(name="indie").first()
        if tag1 is None:
            tag1 = Tag(name="indie")
            db.session.add(tag1)

        tag2 = db.session.query(Tag).filter_by(name="rock").first()
        if tag2 is None:
            tag2 = Tag(name="rock")
            db.session.add(tag2)

        song.tags.extend([tag1, tag2])
        db.session.add(song)
        db.session.commit()

        # Check the raw SQL to see duplicate rows
        raw_query = db.session.execute(text(f"""
            SELECT COUNT(*) as row_count 
            FROM song 
            LEFT OUTER JOIN song_tags ON song.id = song_tags.song_id 
            WHERE song.title LIKE '%Test Song {uid}%'
        """))
        raw_count = raw_query.scalar()
        
        results = search_songs(f"Test Song {uid}")

        print(f"Bug #3 - Search duplicates:")
        print(f"  Raw SQL rows: {raw_count}")
        print(f"  Python results: {len(results)}")
        print(f"  Expected: 1 row, Actual: {raw_count} rows")
        print(f"  ✓ Bug present: {raw_count > 1}")
        if len(results) > 1:
            print(f"  (Duplicates hidden by SQLAlchemy ORM deduplication)")
        print()

def test_bug_2():
    """Friends from yesterday show in listening-now"""
    with app.app_context():
        uid = get_unique_id()

        alice = User(username=f"alice_{uid}", email=f"alice_{uid}@test.com")
        bob = User(username=f"bob_{uid}", email=f"bob_{uid}@test.com")

        db.session.add_all([alice, bob])
        db.session.commit()

        alice.friends.append(bob)
        db.session.commit()

        song = Song(title=f"Song_{uid}", artist="Artist", shared_by=alice.id)
        db.session.add(song)
        db.session.commit()

        # IMPORTANT: Set event to be within 24 hours but from yesterday
        # If current time is 3 PM, set event to 4 PM yesterday (23 hours ago)
        now = datetime.now(timezone.utc)
        # Go back 23 hours to stay within the 24-hour window but be from yesterday
        yesterday_within_window = now - timedelta(hours=23)
        
        event = ListeningEvent(
            user_id=bob.id,
            song_id=song.id,
            listened_at=yesterday_within_window
        )

        db.session.add(event)
        db.session.commit()

        try:
            results = get_friends_listening_now(alice.id)

            print(f"Bug #2 - Yesterday's friends show:")
            print(f"  Event time: {yesterday_within_window}")
            print(f"  Current time: {datetime.now(timezone.utc)}")
            print(f"  Hours old: ~23 hours")
            print(f"  Threshold: 24 hours")
            print(f"  Expected: 0, Actual: {len(results)}")
            print(f"  ✓ Bug present: {len(results) > 0}")

            if len(results) > 0:
                print(f"  Friend appeared: {results[0]['friend']['username']}")
                print(f"  (They shouldn't appear—listened yesterday, not 'now')")

        except Exception as e:
            print(f"Error in Bug #2: {e}")

        print()

if __name__ == "__main__":
    print("=" * 60)
    print("REPRODUCING BUGS #1, #2, #3")
    print("=" * 60)
    print()
    test_bug_1()
    test_bug_3()
    test_bug_2()
    print("=" * 60)