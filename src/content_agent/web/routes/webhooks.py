import json
import logging
import os

from fastapi import APIRouter, Request, Response
from svix.webhooks import Webhook, WebhookVerificationError

from content_agent.queries import orgs
from content_agent.web.deps import get_conn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/clerk")
async def clerk_webhook(request: Request) -> Response:
    secret = os.environ.get("CLERK_WEBHOOK_SECRET", "")
    body = await request.body()
    headers = dict(request.headers)

    try:
        wh = Webhook(secret)
        payload = wh.verify(body, headers)
    except WebhookVerificationError:
        logger.warning("Clerk webhook signature verification failed")
        return Response(status_code=400)

    event_type = payload.get("type", "")
    data = payload.get("data", {})

    conn = get_conn(request)
    try:
        if event_type == "organization.created":
            orgs.upsert_org(conn, data["id"], data["name"], data.get("slug"), data.get("image_url"))
        elif event_type == "organization.updated":
            orgs.upsert_org(conn, data["id"], data["name"], data.get("slug"), data.get("image_url"))
        elif event_type == "organization.deleted":
            orgs.delete_org(conn, data["id"])
        elif event_type == "organizationMembership.created":
            org_data = data.get("organization", {})
            user_data = data.get("public_user_data", {})
            orgs.upsert_org_member(conn, org_data["id"], user_data["user_id"], data.get("role", "org:member"))
        elif event_type == "organizationMembership.deleted":
            org_data = data.get("organization", {})
            user_data = data.get("public_user_data", {})
            orgs.remove_org_member(conn, org_data["id"], user_data["user_id"])
        else:
            return Response(status_code=204)
    finally:
        conn.close()

    return Response(status_code=200)
