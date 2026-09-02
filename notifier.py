"""
Notification module.

Sends desktop toast notifications (Windows) and optional email alerts
when case status changes or silent updates are detected.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config

logger = logging.getLogger(__name__)

# Severity → emoji mapping
SEVERITY_ICONS = {
    "alert": "[!!]",
    "warning": "[!]",
    "info": "[i]",
}


def send_desktop_notification(title: str, message: str, severity: str = "info") -> None:
    """Send a Windows desktop toast notification."""
    if not config.ENABLE_DESKTOP_NOTIFICATIONS:
        return

    try:
        from plyer import notification

        icon = SEVERITY_ICONS.get(severity, "ℹ️")
        notification.notify(
            title=f"{icon} USCIS: {title}",
            message=message[:256],  # Windows toast has a character limit
            app_name="USCIS Case Tracker",
            timeout=10,
        )
        logger.info("Desktop notification sent: %s", title)
    except ImportError:
        logger.warning("plyer not installed. Skipping desktop notification.")
    except Exception as e:
        logger.error("Desktop notification failed: %s", e)


def send_email_notification(subject: str, body_html: str) -> None:
    """Send an email notification via SMTP."""
    if not config.ENABLE_EMAIL_NOTIFICATIONS:
        return

    if not all([config.SMTP_USERNAME, config.SMTP_PASSWORD, config.EMAIL_TO]):
        logger.warning("Email notifications enabled but SMTP credentials not configured.")
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"USCIS Update: {subject}"
        msg["From"] = config.SMTP_USERNAME
        msg["To"] = config.EMAIL_TO

        # Plain text fallback
        plain = body_html.replace("<br>", "\n").replace("<b>", "").replace("</b>", "")
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("Email notification sent: %s", subject)

    except Exception as e:
        logger.error("Email notification failed: %s", e)


def notify_changes(receipt_number: str, changes: list[dict]) -> None:
    """
    Process a list of detected changes and send appropriate notifications.
    """
    if not changes:
        return

    for change in changes:
        severity = change.get("severity", "info")
        change_type = change.get("type", "")
        description = change.get("description", "")

        # Skip "first fetch" from triggering notifications
        if change_type == "first_fetch":
            logger.info("First fetch for %s — no notification sent.", receipt_number)
            continue

        # Desktop notification
        send_desktop_notification(
            title=f"{receipt_number}",
            message=description,
            severity=severity,
        )

        # Email notification (only for alert-level changes)
        if severity in ("alert", "warning"):
            send_email_notification(
                subject=f"{receipt_number} — {change_type.replace('_', ' ').title()}",
                body_html=_build_email_body(receipt_number, change),
            )


def _build_email_body(receipt_number: str, change: dict) -> str:
    """Build a simple HTML email body for a change notification."""
    icon = SEVERITY_ICONS.get(change.get("severity", "info"), "ℹ️")
    return f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); 
                    color: white; padding: 24px; border-radius: 12px 12px 0 0;">
            <h2 style="margin: 0;">{icon} USCIS Case Update</h2>
            <p style="margin: 8px 0 0; opacity: 0.8;">Receipt: {receipt_number}</p>
        </div>
        <div style="background: #f8f9fa; padding: 24px; border-radius: 0 0 12px 12px;
                    border: 1px solid #e9ecef;">
            <p style="font-size: 16px; color: #333;">
                <b>Change Type:</b> {change.get('type', '').replace('_', ' ').title()}
            </p>
            <p style="font-size: 14px; color: #555;">{change.get('description', '')}</p>
            <hr style="border: none; border-top: 1px solid #dee2e6; margin: 16px 0;">
            <p style="font-size: 12px; color: #888;">
                Detected at: {change.get('detected_at', 'N/A')}<br>
                View your dashboard at http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}
            </p>
        </div>
    </div>
    """
