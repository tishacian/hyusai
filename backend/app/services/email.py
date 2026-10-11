"""SMTP email sender — synchronous smtplib wrapped in an executor for async callers."""
import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpDeliveryConfig:
    host: str
    port: int = 465
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = "Agentium"
    use_ssl: bool = True
    use_starttls: bool = True
    timeout_seconds: float = 15.0


def _default_delivery_config() -> SmtpDeliveryConfig:
    return SmtpDeliveryConfig(
        host=settings.smtp_host or "",
        port=settings.smtp_port,
        username=settings.smtp_user or "",
        password=settings.smtp_password or "",
        from_email=settings.smtp_from or settings.smtp_user or "",
        from_name=settings.smtp_from_name,
        use_ssl=settings.smtp_ssl,
        use_starttls=not settings.smtp_ssl,
    )


def _build_message(
    to: str,
    subject: str,
    html: str,
    text: Optional[str],
    config: Optional[SmtpDeliveryConfig] = None,
) -> EmailMessage:
    cfg = config or _default_delivery_config()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = to
    msg["From"] = formataddr((cfg.from_name, cfg.from_email or cfg.username))
    msg.set_content(text or "This email requires an HTML-capable client.")
    msg.add_alternative(html, subtype="html")
    return msg


def _send_sync(to: str, subject: str, html: str, text: Optional[str], config: Optional[SmtpDeliveryConfig] = None) -> bool:
    cfg = config or _default_delivery_config()
    if not (cfg.host and cfg.username and cfg.password):
        logger.warning("SMTP not configured; skipping email to %s", to)
        return False

    msg = _build_message(to, subject, html, text, cfg)

    try:
        if cfg.use_ssl:
            with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout_seconds) as s:
                s.login(cfg.username, cfg.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout_seconds) as s:
                if cfg.use_starttls:
                    s.starttls()
                s.login(cfg.username, cfg.password)
                s.send_message(msg)
        return True
    except Exception:
        logger.exception("SMTP send failed for %s", to)
        return False


async def send_email(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _send_sync, to, subject, html, text)


def send_email_with_config(
    *,
    config: SmtpDeliveryConfig,
    to: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
) -> bool:
    return _send_sync(to, subject, html, text, config)


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
