from typing import Annotated, Optional

import psycopg2
import psycopg2.extras
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError

from content_agent.models import AgentConfig
from content_agent.web.auth import ClerkJWTVerifier, UserContext


def get_conn(request: Request):
    """Open a per-request PostgreSQL connection using config from app state."""
    config: AgentConfig = request.app.state.config
    return psycopg2.connect(config.database_url, cursor_factory=psycopg2.extras.RealDictCursor)


def _extract_token(request: Request) -> Optional[str]:
    token = request.cookies.get("__session")
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def get_current_user(request: Request) -> UserContext:
    verifier: ClerkJWTVerifier = request.app.state.clerk_verifier

    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        claims = verifier.verify_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Sync user on first seen
    from content_agent.queries.users import get_user, upsert_user

    conn = get_conn(request)
    try:
        if not get_user(conn, user_id):
            upsert_user(conn, user_id, claims.get("email"), None, None)
    finally:
        conn.close()

    return UserContext(
        user_id=user_id,
        email=claims.get("email"),
        active_org_id=claims.get("org_id"),
        org_role=claims.get("org_role"),
    )


CurrentUser = Annotated[UserContext, Depends(get_current_user)]
