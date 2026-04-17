"""SMTP email sender — synchronous smtplib wrapped in an executor for async callers."""
import asyncio
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_message(to: str, subject: str, html: str, text: Optional[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = to
    msg["From"] = formataddr((settings.smtp_from_name, settings.smtp_from or settings.smtp_user or ""))
    msg.set_content(text or "This email requires an HTML-capable client.")
    msg.add_alternative(html, subtype="html")
    return msg


def _send_sync(to: str, subject: str, html: str, text: Optional[str]) -> bool:
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_password):
        logger.warning("SMTP not configured; skipping email to %s", to)
        return False

    msg = _build_message(to, subject, html, text)

    try:
        if settings.smtp_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as s:
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
                s.starttls()
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        return True
    except Exception:
        logger.exception("SMTP send failed for %s", to)
        return False


async def send_email(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _send_sync, to, subject, html, text)


def render_mfa_email(code: str, full_name: Optional[str], ttl_minutes: int) -> tuple[str, str, str]:
    """Return (subject, html, text) for an MFA OTP email."""
    name = full_name or "there"
    subject = f"[Agentium] Code de verification : {code}"
    text = (
        f"Votre code de verification Agentium : {code} (valable {ttl_minutes} min)\n"
        f"Si vous n'etes pas a l'origine de cette demande, ignorez ce message."
    )
    html = f"""<!DOCTYPE html>
<html><body style="font-family:system-ui,-apple-system,sans-serif;background:#f8fafc;margin:0;padding:32px;">
  <div style="max-width:520px;margin:auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb;">
    <div style="background:linear-gradient(135deg,#0ea5e9,#6366f1);padding:24px;color:#fff;">
      <h1 style="margin:0;font-size:22px;">Agentium</h1>
      <p style="margin:4px 0 0;opacity:.85;font-size:14px;">Verification d'identite</p>
    </div>
    <div style="padding:28px;">
      <p style="margin:0 0 12px;color:#0f172a;">Bonjour {name},</p>
      <p style="margin:0 0 20px;color:#475569;">Voici votre code de verification :</p>
      <div style="font-size:32px;letter-spacing:10px;font-weight:700;color:#0f172a;background:#f1f5f9;
                  padding:16px 24px;border-radius:12px;text-align:center;border:1px dashed #cbd5e1;">
        {code}
      </div>
      <p style="margin:20px 0 0;color:#64748b;font-size:13px;">
        Ce code est valable {ttl_minutes} minutes. Ne le partagez avec personne.<br/>
        Si vous n'etes pas a l'origine de cette demande, ignorez cet email.
      </p>
    </div>
    <div style="padding:16px 28px;border-top:1px solid #f1f5f9;color:#94a3b8;font-size:11px;">
      Agentium &middot; This is an automated message, please do not reply.
    </div>
  </div>
</body></html>"""
    return subject, html, text
