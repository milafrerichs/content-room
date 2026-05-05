"""
Sync existing Clerk organizations and their members into the database.

Run this once after enabling org support on a database that already has orgs
in Clerk. New orgs arrive via the /webhooks/clerk endpoint automatically.

Requires CLERK_SECRET_KEY and DATABASE_URL environment variables.

Usage:
    DATABASE_URL=postgresql://... CLERK_SECRET_KEY=sk_live_... uv run python scripts/sync_orgs.py

The script is idempotent — re-running it is safe.
"""

import os
import sys

import psycopg2
import psycopg2.extras
import urllib.request
import urllib.error
import json


def clerk_get(path: str, secret_key: str) -> dict | list:
    url = f"https://api.clerk.com/v1{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {secret_key}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_all_pages(path: str, secret_key: str) -> list[dict]:
    """Fetch all pages from a paginated Clerk endpoint."""
    results = []
    offset = 0
    limit = 100
    while True:
        sep = "&" if "?" in path else "?"
        data = clerk_get(f"{path}{sep}limit={limit}&offset={offset}", secret_key)
        # Clerk returns either a list directly or {"data": [...], "total_count": N}
        if isinstance(data, list):
            results.extend(data)
            break
        items = data.get("data", [])
        results.extend(items)
        if offset + limit >= data.get("total_count", len(items)):
            break
        offset += limit
    return results


def main() -> None:
    secret_key = os.environ.get("CLERK_SECRET_KEY")
    db_url = os.environ.get("DATABASE_URL")

    if not secret_key:
        print("ERROR: CLERK_SECRET_KEY environment variable is required", file=sys.stderr)
        sys.exit(1)
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is required", file=sys.stderr)
        sys.exit(1)

    print("Fetching organizations from Clerk...")
    try:
        orgs = fetch_all_pages("/organizations", secret_key)
    except urllib.error.HTTPError as e:
        print(f"ERROR: Clerk API returned {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)

    if not orgs:
        print("No organizations found in Clerk.")
        return

    print(f"Found {len(orgs)} organization(s).")
    for org in orgs:
        print(f"  {org['id']}  {org['name']}")

    confirm = input(f"\nSync {len(orgs)} org(s) and their members into the database? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur = conn.cursor()
        orgs_upserted = 0
        members_upserted = 0

        for org in orgs:
            cur.execute(
                """INSERT INTO organizations (clerk_id, name, slug, image_url)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (clerk_id) DO UPDATE SET
                       name = EXCLUDED.name,
                       slug = EXCLUDED.slug,
                       image_url = EXCLUDED.image_url""",
                (org["id"], org["name"], org.get("slug"), org.get("image_url")),
            )
            orgs_upserted += 1

            # Fetch members for this org
            memberships = fetch_all_pages(f"/organizations/{org['id']}/memberships", secret_key)
            for m in memberships:
                pub_user = m.get("public_user_data", {})
                user_id = pub_user.get("user_id") or m.get("user_id")
                if not user_id:
                    continue
                role = m.get("role", "org:member")

                # Ensure the user row exists (may not have logged in yet)
                cur.execute(
                    """INSERT INTO users (clerk_id, email, display_name)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (clerk_id) DO NOTHING""",
                    (
                        user_id,
                        pub_user.get("primary_email_address_id"),
                        pub_user.get("identifier"),
                    ),
                )

                cur.execute(
                    """INSERT INTO org_members (org_id, user_id, role)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role""",
                    (org["id"], user_id, role),
                )
                members_upserted += 1

        conn.commit()
        print(f"\nDone. Upserted {orgs_upserted} org(s) and {members_upserted} member(s).")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
