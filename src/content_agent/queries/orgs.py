from typing import Optional

from content_agent.db import _execute, _fetchall, _fetchone


def upsert_org(
    conn,
    clerk_id: str,
    name: str,
    slug: Optional[str] = None,
    image_url: Optional[str] = None,
) -> None:
    _execute(
        conn,
        """INSERT INTO organizations (clerk_id, name, slug, image_url)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (clerk_id) DO UPDATE SET name=EXCLUDED.name, slug=EXCLUDED.slug, image_url=EXCLUDED.image_url""",
        (clerk_id, name, slug, image_url),
    )


def delete_org(conn, clerk_id: str) -> None:
    _execute(conn, "DELETE FROM organizations WHERE clerk_id = %s", (clerk_id,))


def upsert_org_member(conn, org_id: str, user_id: str, role: str = "org:member") -> None:
    _execute(
        conn,
        """INSERT INTO org_members (org_id, user_id, role)
           VALUES (%s, %s, %s)
           ON CONFLICT (org_id, user_id) DO UPDATE SET role=EXCLUDED.role""",
        (org_id, user_id, role),
    )


def remove_org_member(conn, org_id: str, user_id: str) -> None:
    _execute(
        conn,
        "DELETE FROM org_members WHERE org_id = %s AND user_id = %s",
        (org_id, user_id),
    )


def get_user_orgs(conn, user_id: str) -> list[dict]:
    return _fetchall(
        conn,
        """SELECT o.clerk_id, o.name, o.slug, o.image_url, om.role
           FROM org_members om
           JOIN organizations o ON o.clerk_id = om.org_id
           WHERE om.user_id = %s
           ORDER BY o.name""",
        (user_id,),
    )
