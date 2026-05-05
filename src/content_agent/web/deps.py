import logging
from typing import Annotated, Optional

import psycopg2
import psycopg2.extras
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError

from content_agent.models import AgentConfig
from content_agent.web.auth import ClerkJWTVerifier, UserContext, extract_token

logger = logging.getLogger(__name__)


def get_conn(request: Request):
    """Open a per-request PostgreSQL connection using config from app state."""
    config: AgentConfig = request.app.state.config
    return psycopg2.connect(config.database_url, cursor_factory=psycopg2.extras.RealDictCursor)


def get_current_user(request: Request) -> UserContext:
    verifier: ClerkJWTVerifier = request.app.state.clerk_verifier

    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        claims = verifier.verify_token(token)
    except JWTError as exc:
        logger.info("JWT verification failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    from content_agent.queries.users import get_user, upsert_user
    from content_agent.queries.orgs import get_user_orgs

    conn = get_conn(request)
    try:
        if not get_user(conn, user_id):
            logger.info("First login for user %s", user_id)
            upsert_user(conn, user_id, claims.get("email"), None, None)

        orgs = get_user_orgs(conn, user_id)
        all_org_ids = [o["clerk_id"] for o in orgs]
    finally:
        conn.close()

    active_org_id = claims.get("org_id") or request.cookies.get("active_org_id")
    if active_org_id and active_org_id not in all_org_ids:
        active_org_id = None

    org_role = claims.get("org_role")
    if not org_role and active_org_id:
        for o in orgs:
            if o["clerk_id"] == active_org_id:
                org_role = o["role"]
                break

    return UserContext(
        user_id=user_id,
        email=claims.get("email"),
        active_org_id=active_org_id,
        org_role=org_role,
        all_org_ids=all_org_ids,
    )


CurrentUser = Annotated[UserContext, Depends(get_current_user)]
