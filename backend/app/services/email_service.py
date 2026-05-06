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
