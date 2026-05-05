import logging
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

import requests as http_requests
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

_CLOCK_LEEWAY = 30  # seconds


@dataclass(frozen=True)
class Owner:
    """Value object representing the owner of a feed or item."""
    type: Literal["user", "org", "team"]
    id: str

    @classmethod
    def user(cls, user_id: str) -> "Owner":
        return cls(type="user", id=user_id)

    @classmethod
    def org(cls, org_id: str) -> "Owner":
        return cls(type="org", id=org_id)

    @classmethod
    def team(cls, team_id: str) -> "Owner":
        return cls(type="team", id=team_id)


@dataclass
class UserContext:
    user_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    active_org_id: Optional[str] = None
    org_role: Optional[str] = None
    team_ids: list[str] = field(default_factory=list)
    all_org_ids: list[str] = field(default_factory=list)

    @property
    def owner(self) -> Owner:
        return Owner.user(self.user_id)


def extract_token(request) -> Optional[str]:
    """Extract a bearer token from the __session cookie or Authorization header."""
    token = request.cookies.get("__session")
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


class ClerkJWTVerifier:
    def __init__(self, jwks_url: str, issuer: str):
        self._jwks_url = jwks_url
        self._issuer = issuer
        self._jwks: Optional[dict] = None
        self._jwks_fetched_at: float = 0
        self._jwks_ttl = 3600

    def _get_jwks(self) -> dict:
        now = time.time()
        if self._jwks is None or (now - self._jwks_fetched_at) > self._jwks_ttl:
            resp = http_requests.get(self._jwks_url, timeout=10)
            resp.raise_for_status()
            self._jwks = resp.json()
            self._jwks_fetched_at = now
            logger.debug("Refreshed Clerk JWKS from %s", self._jwks_url)
        return self._jwks

    def verify_token(self, token: str) -> dict:
        """Verify a Clerk JWT and return its claims. Raises JWTError on failure."""
        jwks = self._get_jwks()
        return jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            issuer=self._issuer,
            options={"leeway": _CLOCK_LEEWAY, "verify_aud": False},
        )
