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
