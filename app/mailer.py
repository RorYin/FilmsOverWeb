import smtplib
import secrets
import string
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Tuple, Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.models import SystemSetting

def generate_secure_password(length: int = 12) -> str:
    """Generates a secure, readable random password containing upper, lower, digits, and special chars."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    # Ensure at least one of each required group
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%&*")
    ]
    password += [secrets.choice(alphabet) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(password)
    return "".join(password)

def get_smtp_config(db: Optional[Session] = None) -> dict:
    config = {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "user": settings.SMTP_USER,
        "password": settings.SMTP_PASSWORD,
        "use_ssl": settings.SMTP_USE_SSL
    }
    if db:
        for key in ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_use_ssl"]:
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row and row.value is not None and row.value.strip():
                if key == "smtp_port":
                    try:
                        config["port"] = int(row.value.strip())
                    except ValueError:
                        pass
                elif key == "smtp_use_ssl":
                    config["use_ssl"] = row.value.strip().lower() in ("true", "1", "yes")
                else:
                    config[key.replace("smtp_", "")] = row.value.strip()

    return config

def send_guest_welcome_email(
    guest_email: str,
    guest_name: Optional[str],
    password: str,
    login_url: str,
    db: Optional[Session] = None
) -> Tuple[bool, str]:
    """
    Automates sending the welcome email with credentials to newly created guest accounts
    using Google Mail (drmnbot@gmail.com).
    """
    cfg = get_smtp_config(db)
    sender = cfg["user"] or "drmnbot@gmail.com"
    password_smtp = cfg["password"]

    if not password_smtp:
        return False, "Gmail App Password is not configured in SuperAdmin Settings yet. Generated credentials saved successfully."

    subject = "🎬 Your FilmsOverWeb Access is Ready - Welcome to the Cinema"
    display_name = guest_name if guest_name else "Guest"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0c0e; color: #e5e7eb; margin: 0; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #14171f; border-radius: 12px; border: 1px solid #222734; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
            .header {{ background: linear-gradient(135deg, #e50914 0%, #b20710 100%); padding: 30px; text-align: center; }}
            .header h1 {{ margin: 0; color: #ffffff; font-size: 26px; font-weight: 800; letter-spacing: 1px; }}
            .body-content {{ padding: 30px; }}
            .credential-box {{ background: #1c212d; border-radius: 8px; border: 1px dashed #3b82f6; padding: 20px; margin: 25px 0; text-align: center; }}
            .credential-item {{ margin: 8px 0; font-size: 15px; color: #94a3b8; }}
            .credential-value {{ font-family: 'Courier New', Courier, monospace; font-size: 18px; color: #38bdf8; font-weight: bold; background: #0f172a; padding: 4px 12px; border-radius: 4px; display: inline-block; margin-top: 4px; }}
            .cta-button {{ display: inline-block; background: #e50914; color: #ffffff !important; text-decoration: none; font-weight: bold; padding: 14px 28px; border-radius: 6px; font-size: 16px; margin-top: 20px; box-shadow: 0 4px 14px rgba(229, 9, 20, 0.4); }}
            .feature-tag {{ display: inline-block; background: rgba(56, 189, 248, 0.1); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); padding: 4px 10px; border-radius: 15px; font-size: 12px; margin: 4px 2px; }}
            .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #64748b; border-top: 1px solid #1e2430; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>FILMS OVER WEB</h1>
                <p style="margin: 5px 0 0; color: rgba(255,255,255,0.85); font-size: 14px;">Your Private Cloud Cinema Library</p>
            </div>
            <div class="body-content">
                <h2 style="margin-top: 0; color: #ffffff;">Hello {display_name},</h2>
                <p style="line-height: 1.6; color: #cbd5e1;">You have been invited as a <strong>Guest</strong> to browse and watch movies directly from Google Drive in full, uncompressed cinema quality.</p>
                
                <div style="margin: 15px 0;">
                    <span class="feature-tag">✨ Full Quality Direct Stream</span>
                    <span class="feature-tag">🚀 HEVC / H.265 Accelerated</span>
                    <span class="feature-tag">⚡ AV1 Codec Supported</span>
                    <span class="feature-tag">🍿 OTT Netflix-style UI</span>
                </div>

                <div class="credential-box">
                    <div class="credential-item">Your Login Email:</div>
                    <div class="credential-value">{guest_email}</div>
                    <div style="height: 12px;"></div>
                    <div class="credential-item">Auto-Generated Temporary Password:</div>
                    <div class="credential-value">{password}</div>
                </div>

                <div style="text-align: center;">
                    <a href="{login_url}" class="cta-button">Launch FilmsOverWeb Now &rarr;</a>
                </div>

                <p style="font-size: 13px; color: #94a3b8; margin-top: 30px; line-height: 1.5;">
                    💡 <em>Tip for best playback: Modern browsers like Google Chrome, Microsoft Edge, and Safari have built-in hardware acceleration for HEVC and AV1.</em>
                </p>
            </div>
            <div class="footer">
                Automated by FilmsOverWeb System &bull; Sent from {sender}<br>
                Please keep your credentials safe.
            </div>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"FilmsOverWeb <{sender}>"
    msg["To"] = guest_email

    text_content = f"""
Hello {display_name},

Your FilmsOverWeb Guest account has been created!
Login Email: {guest_email}
Password: {password}
Login URL: {login_url}

Enjoy movies streamed directly from Google Drive in full quality with HEVC and AV1 support.
    """

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        if cfg["use_ssl"]:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15) as server:
                server.login(sender, password_smtp)
                server.sendmail(sender, [guest_email], msg.as_string())
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
                server.starttls()
                server.login(sender, password_smtp)
                server.sendmail(sender, [guest_email], msg.as_string())
        return True, "Email sent successfully via Gmail automation."
    except Exception as e:
        err_msg = str(e)
        print(f"[MAILER] Error sending email to {guest_email}: {err_msg}")
        return False, f"Failed to send email: {err_msg}"
