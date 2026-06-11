"""Web Push (VAPID) sender.

Mirrors the email service's "empty config = disabled" convention: when the
VAPID keys are unset (the dev default) ``send_to_user`` logs and returns instead
of sending, so local dev and the no-cost prompt builds never need a keypair.

Sending is best-effort — every failure is logged-and-swallowed so a flaky push
service can't take down an audit run or a competitor refresh. Endpoints the push
service reports as gone (HTTP 404 / 410) are pruned.

``pywebpush`` is imported lazily inside the send path so this module (and the
workers that import it) load fine even before the dependency is installed — you
only need it once VAPID keys are configured.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models.push_subscription import PushSubscription

logger = logging.getLogger(__name__)


def vapid_configured() -> bool:
    """True when a VAPID keypair is set — i.e. push can actually be sent."""
    return bool(settings.vapid_private_key and settings.vapid_public_key)


def send_to_user(
    db: Session,
    user_id: int,
    *,
    title: str,
    body: str,
    url: str = "/",
) -> int:
    """Push ``{title, body, url}`` to every subscription a user has.

    Returns the count handed to the push service (0 in dev, or when the user
    has no subscriptions). Best-effort: each failure is swallowed; 404/410
    endpoints (browser unsubscribed / expired) are pruned.
    """
    if not vapid_configured():
        # Dev fallback — keeps the local workflow working without a keypair,
        # same idea as the email service printing the magic link to stdout.
        logger.info(
            "[push:dev] would notify user_id=%s title=%r body=%r url=%r",
            user_id,
            title,
            body,
            url,
        )
        return 0

    subs = (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id == user_id)
        .all()
    )
    if not subs:
        return 0

    # Lazy import: only needed once VAPID is configured, so a worker that never
    # sends (dev, no keys) doesn't require the dependency to be installed.
    from pywebpush import WebPushException, webpush

    payload = json.dumps({"title": title, "body": body, "url": url})
    sent = 0
    dead: list[int] = []
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                # Fresh dict per call — pywebpush augments the claims (adds
                # ``aud``/``exp``) in place.
                vapid_claims={"sub": settings.vapid_subject},
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                # Subscription is gone — prune so we stop trying it.
                dead.append(sub.id)
            else:
                logger.warning(
                    "webpush failed (status=%s) for sub_id=%s", status, sub.id
                )
        except Exception:
            logger.exception("webpush unexpected error for sub_id=%s", sub.id)

    if dead:
        db.query(PushSubscription).filter(
            PushSubscription.id.in_(dead)
        ).delete(synchronize_session=False)
        db.commit()

    return sent
