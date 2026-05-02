from typing import Optional

from content_agent.db import _execute, _fetchone


def upsert_user(
    conn,
    clerk_id: str,
    email: Optional[str],
    display_name: Optional[str],
    image_url: Optional[str],
) -> None:
    _execute(
        conn,
        """
        INSERT INTO users (clerk_id, email, display_name, image_url)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (clerk_id) DO UPDATE SET
            email = EXCLUDED.email,
            display_name = EXCLUDED.display_name,
            image_url = EXCLUDED.image_url
        """,
        (clerk_id, email, display_name, image_url),
    )


def get_user(conn, clerk_id: str) -> Optional[dict]:
    return _fetchone(conn, "SELECT * FROM users WHERE clerk_id = %s", (clerk_id,))


def has_legacy_data(conn) -> bool:
    row = _fetchone(
        conn,
        "SELECT 1 FROM podcast_feeds WHERE owner_id = '__legacy__' LIMIT 1",
    )
    return row is not None


def claim_legacy_data(conn, clerk_id: str) -> None:
    _execute(
        conn,
        "UPDATE podcast_feeds SET owner_id = %s WHERE owner_id = '__legacy__'",
        (clerk_id,),
    )
    _execute(
        conn,
        "UPDATE article_feeds SET owner_id = %s WHERE owner_id = '__legacy__'",
        (clerk_id,),
    )
