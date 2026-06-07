"""Transactional email delivery via Resend.

This module is the single seam between the app and our email provider. Other
modules call ``send_magic_link_email(...)``; if we ever swap Resend for SES /
Postmark / Mailgun, only this file changes.

Behavior
--------
* If ``RESEND_API_KEY`` is unset, we fall back to printing the link to stdout.
  This keeps local development working without a Resend account and preserves
  the prompt-7 dev workflow ("magic link prints to backend terminal").
* If ``RESEND_API_KEY`` is set, we send via Resend. Any failure raises
  ``EmailDeliveryError``; the API layer turns that into an HTTP 500 so the
  user knows the request didn't go through.
"""

from __future__ import annotations

import logging

import resend

from app.config import settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when an email could not be handed off to the provider."""


_MAGIC_LINK_SUBJECT = "Your sign-in link for Local SEO Health Monitor"
_PRODUCT_NAME = "Local SEO Health Monitor"
_PRODUCT_TAGLINE = "Apple Watch for your business's online presence."

# Score-change notification (Phase 3) — emitted when an automated audit
# moves the overall score by more than this many points. Kept here, not
# in audit_view.TREND_THRESHOLD, because the email cadence is a product
# decision separate from the dashboard's trend-arrow threshold.
SCORE_CHANGE_NOTIFY_THRESHOLD = 2

# Design-system tokens, mirroring frontend/tailwind.config.js. Email clients
# strip <style> blocks aggressively, so every color is inlined below.
_BG = "#faf8f4"          # canvas (off-white)
_CARD_BG = "#ffffff"
_INK = "#2b2a26"         # canvas.ink (body text)
_MUTED = "#6b6960"       # canvas.muted (secondary text)
_BRAND = "#4f8c5b"       # healthy-500 (sage primary)
_BRAND_DARK = "#3d7048"  # healthy-600
_BORDER = "#e3efe5"      # healthy-100


def _render_magic_link_html(link: str, ttl_minutes: int) -> str:
    """Branded HTML email. Uses table-based layout + inline styles so it
    renders consistently across Gmail, Outlook, Apple Mail, etc."""
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{_MAGIC_LINK_SUBJECT}</title>
  </head>
  <body style="margin:0; padding:0; background-color:{_BG}; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; color:{_INK};">
    <!-- Preheader (hidden in body, surfaces in inbox preview) -->
    <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
      Your one-tap sign-in link for {_PRODUCT_NAME}. Expires in {ttl_minutes} minutes.
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{_BG}; padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px; width:100%;">
            <!-- Header -->
            <tr>
              <td style="padding:0 8px 24px 8px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="font-size:18px; font-weight:600; color:{_INK}; letter-spacing:-0.01em;">
                      <span style="display:inline-block; width:10px; height:10px; background-color:{_BRAND}; border-radius:9999px; margin-right:8px; vertical-align:middle;"></span>
                      {_PRODUCT_NAME}
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Card -->
            <tr>
              <td style="background-color:{_CARD_BG}; border:1px solid {_BORDER}; border-radius:18px; padding:36px 36px 32px 36px;">
                <h1 style="margin:0 0 12px 0; font-size:24px; line-height:1.3; font-weight:600; color:{_INK}; letter-spacing:-0.01em;">
                  Your sign-in link is ready
                </h1>
                <p style="margin:0 0 24px 0; font-size:15px; line-height:1.55; color:{_MUTED};">
                  Tap the button below to sign in to {_PRODUCT_NAME}. No password needed — this link signs you in directly.
                </p>

                <!-- CTA -->
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 28px 0;">
                  <tr>
                    <td bgcolor="{_BRAND}" style="border-radius:10px;">
                      <a href="{link}" target="_blank" style="display:inline-block; padding:14px 28px; font-size:15px; font-weight:600; color:#ffffff; text-decoration:none; background-color:{_BRAND}; border-radius:10px; border:1px solid {_BRAND_DARK};">
                        Sign in to {_PRODUCT_NAME}
                      </a>
                    </td>
                  </tr>
                </table>

                <p style="margin:0 0 8px 0; font-size:13px; color:{_MUTED};">
                  Or paste this link into your browser:
                </p>
                <p style="margin:0 0 28px 0; font-size:13px; word-break:break-all;">
                  <a href="{link}" target="_blank" style="color:{_BRAND_DARK}; text-decoration:underline;">{link}</a>
                </p>

                <hr style="border:none; border-top:1px solid {_BORDER}; margin:0 0 20px 0;" />

                <p style="margin:0; font-size:13px; line-height:1.55; color:{_MUTED};">
                  This link expires in <strong style="color:{_INK};">{ttl_minutes} minutes</strong> and can only be used once. If you didn't request it, you can safely ignore this email — nobody else can sign in without it.
                </p>
              </td>
            </tr>

            <!-- Footer -->
            <tr>
              <td style="padding:24px 8px 0 8px; font-size:12px; line-height:1.5; color:{_MUTED}; text-align:center;">
                {_PRODUCT_TAGLINE}<br />
                You're receiving this because someone (hopefully you) asked for a sign-in link.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _render_magic_link_text(link: str, ttl_minutes: int) -> str:
    """Plain-text fallback for clients that don't render HTML."""
    return (
        f"{_PRODUCT_NAME}\n"
        f"{'=' * len(_PRODUCT_NAME)}\n\n"
        "Your sign-in link is ready.\n\n"
        f"Tap the link below to sign in to {_PRODUCT_NAME}. No password needed —\n"
        "this link signs you in directly.\n\n"
        f"  {link}\n\n"
        f"This link expires in {ttl_minutes} minutes and can only be used once.\n"
        "If you didn't request it, you can safely ignore this email — nobody\n"
        "else can sign in without it.\n\n"
        "—\n"
        f"{_PRODUCT_TAGLINE}\n"
    )


def send_magic_link_email(to_email: str, link: str) -> None:
    """Deliver a magic-link sign-in email.

    Raises:
        EmailDeliveryError: if Resend rejected the request or threw an error.
            The dev fallback (no API key) never raises.
    """
    ttl = settings.magic_link_ttl_minutes

    if not settings.resend_api_key:
        # Dev fallback — keeps the local workflow working without a Resend
        # account. Production should always have RESEND_API_KEY set.
        print(
            f"\n[magic-link] sign-in link for {to_email}:\n  {link}\n  "
            f"(expires in {ttl} minutes)\n",
            flush=True,
        )
        return

    resend.api_key = settings.resend_api_key
    params = {
        "from": settings.from_email,
        "to": [to_email],
        "subject": _MAGIC_LINK_SUBJECT,
        "html": _render_magic_link_html(link, ttl),
        "text": _render_magic_link_text(link, ttl),
    }
    try:
        resend.Emails.send(params)
    except Exception as exc:
        logger.exception(
            "Resend failed to deliver magic-link email to %s", to_email
        )
        raise EmailDeliveryError(str(exc)) from exc


# --- Score-change notification -----------------------------------------------


def _render_score_change_html(
    business_name: str,
    previous_score: int,
    new_score: int,
    dashboard_url: str,
) -> str:
    """Branded HTML body for the "your score changed" alert.

    Re-uses the same table-based, inline-styled layout as the magic-link
    template so both emails feel like the same product. Color of the
    delta chip flips by direction — sage when the score went up, coral
    when it dipped.
    """
    delta = new_score - previous_score
    direction_label = "went up" if delta > 0 else "dipped"
    delta_text = f"+{delta}" if delta > 0 else str(delta)
    chip_bg = _BRAND if delta > 0 else "#e8806b"  # action-500 (warm coral)
    chip_fg = "#ffffff"
    headline = (
        "Your SEO health score went up"
        if delta > 0
        else "Your SEO health score dipped"
    )
    subject_line = (
        f"Your weekly SEO health score {direction_label} "
        f"from {previous_score} to {new_score}."
    )
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{headline} — {_PRODUCT_NAME}</title>
  </head>
  <body style="margin:0; padding:0; background-color:{_BG}; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; color:{_INK};">
    <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
      {subject_line} View your dashboard to see what changed.
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{_BG}; padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px; width:100%;">
            <tr>
              <td style="padding:0 8px 24px 8px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="font-size:18px; font-weight:600; color:{_INK}; letter-spacing:-0.01em;">
                      <span style="display:inline-block; width:10px; height:10px; background-color:{_BRAND}; border-radius:9999px; margin-right:8px; vertical-align:middle;"></span>
                      {_PRODUCT_NAME}
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td style="background-color:{_CARD_BG}; border:1px solid {_BORDER}; border-radius:18px; padding:36px 36px 32px 36px;">
                <h1 style="margin:0 0 8px 0; font-size:22px; line-height:1.3; font-weight:600; color:{_INK}; letter-spacing:-0.01em;">
                  {headline}
                </h1>
                <p style="margin:0 0 24px 0; font-size:14px; color:{_MUTED};">
                  for <strong style="color:{_INK};">{business_name}</strong>
                </p>

                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 24px 0;">
                  <tr>
                    <td align="center" style="padding-right:24px;">
                      <p style="margin:0 0 4px 0; font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:{_MUTED};">Last week</p>
                      <p style="margin:0; font-size:28px; font-weight:600; color:{_INK};">{previous_score}</p>
                    </td>
                    <td align="center" valign="middle" style="font-size:18px; color:{_MUTED}; padding:0 12px;">→</td>
                    <td align="center" style="padding-left:24px;">
                      <p style="margin:0 0 4px 0; font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:{_MUTED};">This week</p>
                      <p style="margin:0; font-size:28px; font-weight:600; color:{_INK};">{new_score}</p>
                    </td>
                    <td align="center" style="padding-left:20px;">
                      <span style="display:inline-block; padding:6px 12px; background-color:{chip_bg}; color:{chip_fg}; border-radius:9999px; font-size:13px; font-weight:600;">
                        {delta_text}
                      </span>
                    </td>
                  </tr>
                </table>

                <p style="margin:0 0 24px 0; font-size:15px; line-height:1.55; color:{_INK};">
                  Your weekly SEO health score {direction_label} from <strong>{previous_score}</strong> to <strong>{new_score}</strong>. View your dashboard to see what happened and what to do next.
                </p>

                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 28px 0;">
                  <tr>
                    <td bgcolor="{_BRAND}" style="border-radius:10px;">
                      <a href="{dashboard_url}" target="_blank" style="display:inline-block; padding:14px 28px; font-size:15px; font-weight:600; color:#ffffff; text-decoration:none; background-color:{_BRAND}; border-radius:10px; border:1px solid {_BRAND_DARK};">
                        Open my dashboard
                      </a>
                    </td>
                  </tr>
                </table>

                <hr style="border:none; border-top:1px solid {_BORDER}; margin:0 0 20px 0;" />

                <p style="margin:0; font-size:13px; line-height:1.55; color:{_MUTED};">
                  You're getting this because automatic weekly audits are on for your paid plan. We only email you when the overall score changes meaningfully.
                </p>
              </td>
            </tr>

            <tr>
              <td style="padding:24px 8px 0 8px; font-size:12px; line-height:1.5; color:{_MUTED}; text-align:center;">
                {_PRODUCT_TAGLINE}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _render_score_change_text(
    business_name: str,
    previous_score: int,
    new_score: int,
    dashboard_url: str,
) -> str:
    delta = new_score - previous_score
    direction_label = "went up" if delta > 0 else "dipped"
    delta_text = f"+{delta}" if delta > 0 else str(delta)
    return (
        f"{_PRODUCT_NAME}\n"
        f"{'=' * len(_PRODUCT_NAME)}\n\n"
        f"Your weekly SEO health score for {business_name} {direction_label} "
        f"from {previous_score} to {new_score} ({delta_text}).\n\n"
        "View your dashboard to see what happened:\n\n"
        f"  {dashboard_url}\n\n"
        "You're getting this because automatic weekly audits are on for your\n"
        "paid plan. We only email when the overall score changes meaningfully.\n\n"
        "—\n"
        f"{_PRODUCT_TAGLINE}\n"
    )


def send_score_change_email(
    to_email: str,
    business_name: str,
    previous_score: int,
    new_score: int,
    dashboard_url: str,
) -> None:
    """Notify an owner that their overall score moved.

    Same dev-fallback semantics as the magic-link sender: if
    ``RESEND_API_KEY`` is empty, the email body is printed to stdout instead
    of being sent. Unlike the magic-link path, failures here are
    logged-and-swallowed by the caller (``audit_runner``) — a Resend hiccup
    shouldn't tank an otherwise-healthy audit run.
    """
    delta = new_score - previous_score
    direction_label = "went up" if delta > 0 else "dipped"
    subject = (
        f"Your SEO health score for {business_name} {direction_label}"
        f" ({previous_score} → {new_score})"
    )

    if not settings.resend_api_key:
        # Dev fallback — same pattern as the magic-link sender, keeps the
        # local 4-process workflow working without a Resend account.
        print(
            f"\n[score-change] {to_email}: {business_name} "
            f"{previous_score} → {new_score}\n"
            f"  Dashboard: {dashboard_url}\n",
            flush=True,
        )
        return

    resend.api_key = settings.resend_api_key
    params = {
        "from": settings.from_email,
        "to": [to_email],
        "subject": subject,
        "html": _render_score_change_html(
            business_name, previous_score, new_score, dashboard_url
        ),
        "text": _render_score_change_text(
            business_name, previous_score, new_score, dashboard_url
        ),
    }
    try:
        resend.Emails.send(params)
    except Exception as exc:
        logger.exception(
            "Resend failed to deliver score-change email to %s", to_email
        )
        raise EmailDeliveryError(str(exc)) from exc


# --- Weekly digest -----------------------------------------------------------


def _render_weekly_digest_text(payload: dict) -> str:
    """Plain-text digest body. Kept narrow on purpose — a digest opened
    on a phone in 5 seconds should read as glance-able news, not a
    marketing newsletter. HTML can come later; the text version is the
    contract."""
    greeting_name = payload.get("greeting_name") or "there"
    businesses = payload.get("businesses") or []
    lines = [
        f"{_PRODUCT_NAME}",
        "=" * len(_PRODUCT_NAME),
        "",
        f"Hi {greeting_name},",
        "",
        "Here's how your business looked online this week.",
        "",
    ]
    for biz in businesses:
        name = biz.get("name") or "Your business"
        score = biz.get("score")
        delta = biz.get("delta")
        confirmed = biz.get("confirmed_count") or 0
        new_count = biz.get("new_count") or 0
        top = biz.get("top_finding")

        lines.append(f"• {name}")
        if score is not None:
            if delta is None:
                lines.append(f"    Score: {score}/100 (first audit)")
            elif delta > 0:
                lines.append(f"    Score: {score}/100  ↑ +{delta}")
            elif delta < 0:
                lines.append(f"    Score: {score}/100  ↓ {delta}")
            else:
                lines.append(f"    Score: {score}/100  (no change)")
        if confirmed:
            lines.append(f"    ✓ {confirmed} fix{'es' if confirmed != 1 else ''} confirmed since last check")
        if new_count:
            lines.append(f"    ⊕ {new_count} new thing{'s' if new_count != 1 else ''} to look at")
        if top:
            lines.append(f"    Top: {top}")
        lines.append("")

    dashboard_url = payload.get("dashboard_url") or ""
    if dashboard_url:
        lines.append("Open your dashboard:")
        lines.append(f"  {dashboard_url}")
        lines.append("")
    lines.append("You're getting this because weekly digests are on for your paid plan.")
    # NOTE: don't add a STOP / unsubscribe line until the launch-
    # checklist item ("Digest opt-out plumbing") actually ships — until
    # then a working unsubscribe is a promise we can't keep.
    lines.append("")
    lines.append("—")
    lines.append(_PRODUCT_TAGLINE)
    return "\n".join(lines)


def send_weekly_digest_email(to_email: str, payload: dict) -> None:
    """Send (or in dev, print) the user's weekly digest.

    ``payload`` shape comes from ``weekly_digest.build_user_digest``:
    ``{greeting_name, businesses: [{name, score, delta, confirmed_count,
    new_count, top_finding}], dashboard_url}``.

    Like the score-change sender, this swallows Resend failures up the
    call stack — a failed digest is annoying but not load-bearing for
    the user's own actions in the app.
    """
    subject = "Your weekly health check digest"

    if not settings.resend_api_key:
        # Dev fallback — print to the same log the magic-link sender
        # uses so the local 4-process workflow stays predictable.
        print(
            f"\n[weekly-digest] {to_email}:\n"
            f"{_render_weekly_digest_text(payload)}\n",
            flush=True,
        )
        return

    resend.api_key = settings.resend_api_key
    params = {
        "from": settings.from_email,
        "to": [to_email],
        "subject": subject,
        "text": _render_weekly_digest_text(payload),
    }
    try:
        resend.Emails.send(params)
    except Exception as exc:
        logger.exception(
            "Resend failed to deliver weekly digest to %s", to_email
        )
        raise EmailDeliveryError(str(exc)) from exc
