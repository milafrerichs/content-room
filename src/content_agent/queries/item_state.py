from typing import Optional

from content_agent.db import _execute, _fetchone


def upsert_state(
    conn,
    user_id: str,
    item_kind: str,
    item_id: int,
    read_at: Optional[str] = None,
    archived_at: Optional[str] = None,
    read_later_at: Optional[str] = None,
) -> None:
    _execute(
        conn,
        """INSERT INTO user_item_state (user_id, item_kind, item_id, read_at, archived_at, read_later_at)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (user_id, item_kind, item_id) DO UPDATE SET
               read_at = COALESCE(EXCLUDED.read_at, user_item_state.read_at),
               archived_at = EXCLUDED.archived_at,
               read_later_at = EXCLUDED.read_later_at""",
        (user_id, item_kind, item_id, read_at, archived_at, read_later_at),
    )


def mark_read(conn, user_id: str, item_kind: str, item_id: int) -> None:
    _execute(
        conn,
        """INSERT INTO user_item_state (user_id, item_kind, item_id, read_at)
           VALUES (%s, %s, %s, NOW())
           ON CONFLICT (user_id, item_kind, item_id) DO UPDATE SET read_at = NOW()""",
        (user_id, item_kind, item_id),
    )


def archive(conn, user_id: str, item_kind: str, item_id: int) -> None:
    _execute(
        conn,
        """INSERT INTO user_item_state (user_id, item_kind, item_id, archived_at)
           VALUES (%s, %s, %s, NOW())
           ON CONFLICT (user_id, item_kind, item_id) DO UPDATE SET archived_at = NOW()""",
        (user_id, item_kind, item_id),
    )


def unarchive(conn, user_id: str, item_kind: str, item_id: int) -> None:
    _execute(
        conn,
        """INSERT INTO user_item_state (user_id, item_kind, item_id, archived_at)
           VALUES (%s, %s, %s, NULL)
           ON CONFLICT (user_id, item_kind, item_id) DO UPDATE SET archived_at = NULL""",
        (user_id, item_kind, item_id),
    )


def mark_read_later(conn, user_id: str, item_kind: str, item_id: int) -> None:
    _execute(
        conn,
        """INSERT INTO user_item_state (user_id, item_kind, item_id, read_later_at)
           VALUES (%s, %s, %s, NOW())
           ON CONFLICT (user_id, item_kind, item_id) DO UPDATE SET read_later_at = NOW()""",
        (user_id, item_kind, item_id),
    )


def unmark_read_later(conn, user_id: str, item_kind: str, item_id: int) -> None:
    _execute(
        conn,
        """INSERT INTO user_item_state (user_id, item_kind, item_id, read_later_at)
           VALUES (%s, %s, %s, NULL)
           ON CONFLICT (user_id, item_kind, item_id) DO UPDATE SET read_later_at = NULL""",
        (user_id, item_kind, item_id),
    )


def get_state(conn, user_id: str, item_kind: str, item_id: int) -> Optional[dict]:
    return _fetchone(
        conn,
        "SELECT * FROM user_item_state WHERE user_id = %s AND item_kind = %s AND item_id = %s",
        (user_id, item_kind, item_id),
    )
