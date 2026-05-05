"""
Assign all unowned feeds to a specific Clerk user.

Run this after `alembic upgrade head` on an existing single-user database to
claim all podcast_feeds and article_feeds for a real Clerk user ID.

Usage:
    DATABASE_URL=postgresql://... uv run python scripts/migrate_to_user.py <clerk_user_id>

Example:
    DATABASE_URL=postgresql://localhost/content_agent uv run python scripts/migrate_to_user.py user_2abc123

The script is idempotent — re-running with the same user ID is safe.
"""

import argparse
import os
import sys

import psycopg2
import psycopg2.extras


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign unowned feeds to a Clerk user")
    parser.add_argument("clerk_user_id", help="Clerk user ID, e.g. user_2abc123...")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is required", file=sys.stderr)
        sys.exit(1)

    clerk_id = args.clerk_user_id
    if not clerk_id.startswith("user_"):
        print(f"WARNING: '{clerk_id}' does not look like a Clerk user ID (expected 'user_...')")
        confirm = input("Continue anyway? [y/N] ").strip().lower()
        if confirm != "y":
            sys.exit(0)

    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur = conn.cursor()

        # Ensure the user row exists
        cur.execute(
            "INSERT INTO users (clerk_id) VALUES (%s) ON CONFLICT (clerk_id) DO NOTHING",
            (clerk_id,),
        )
        print(f"User row ensured for {clerk_id}")

        # Show what will be updated — catches NULL, empty string, and legacy 'system' owner
        cur.execute(
            "SELECT COUNT(*) as n FROM podcast_feeds WHERE owner_id IS NULL OR owner_id IN ('', 'system')"
        )
        n_podcasts = cur.fetchone()["n"]
        cur.execute(
            "SELECT COUNT(*) as n FROM article_feeds WHERE owner_id IS NULL OR owner_id IN ('', 'system')"
        )
        n_articles = cur.fetchone()["n"]

        if n_podcasts == 0 and n_articles == 0:
            print("No unowned feeds found — nothing to migrate.")
            conn.commit()
            return

        print(f"\nWill assign to {clerk_id}:")
        print(f"  {n_podcasts} podcast feed(s) (owner_id IS NULL, '', or 'system')")
        print(f"  {n_articles} article feed(s) (owner_id IS NULL, '', or 'system')")
        confirm = input("\nProceed? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

        cur.execute(
            "UPDATE podcast_feeds SET owner_type = 'user', owner_id = %s"
            " WHERE owner_id IS NULL OR owner_id IN ('', 'system')",
            (clerk_id,),
        )
        print(f"Updated {cur.rowcount} podcast feed(s)")

        cur.execute(
            "UPDATE article_feeds SET owner_type = 'user', owner_id = %s"
            " WHERE owner_id IS NULL OR owner_id IN ('', 'system')",
            (clerk_id,),
        )
        print(f"Updated {cur.rowcount} article feed(s)")

        conn.commit()
        print("\nDone.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
