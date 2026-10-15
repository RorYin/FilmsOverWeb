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
    password_smtp = (cfg["password"] or "").strip().replace(" ", "")

    if not password_smtp:
        return False, "Google App Password is not configured in SuperAdmin Settings yet. Please generate one at https://myaccount.google.com/apppasswords and paste it in Settings."

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
            .header {{ background: linear-gradient(135deg, #e5a00d 0%, #c78707 100%); padding: 30px; text-align: center; }}
            .header h1 {{ margin: 0; color: #0b0c0e; font-size: 26px; font-weight: 900; letter-spacing: 1.5px; }}
            .body-content {{ padding: 30px; }}
            .credential-box {{ background: #1c212d; border-radius: 8px; border: 1px dashed #e5a00d; padding: 20px; margin: 25px 0; text-align: center; }}
            .credential-item {{ margin: 8px 0; font-size: 15px; color: #94a3b8; }}
            .credential-value {{ font-family: 'Courier New', Courier, monospace; font-size: 18px; color: #fbbf24; font-weight: bold; background: #0f172a; padding: 4px 12px; border-radius: 4px; display: inline-block; margin-top: 4px; }}
            .cta-button {{ display: inline-block; background: #e5a00d; color: #0b0c0e !important; text-decoration: none; font-weight: 900; padding: 14px 28px; border-radius: 8px; font-size: 16px; margin-top: 20px; box-shadow: 0 4px 14px rgba(229, 160, 13, 0.4); }}
            .feature-tag {{ display: inline-block; background: rgba(229, 160, 13, 0.1); color: #fbbf24; border: 1px solid rgba(229, 160, 13, 0.3); padding: 4px 10px; border-radius: 15px; font-size: 12px; margin: 4px 2px; }}
            .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #64748b; border-top: 1px solid #1e2430; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>FILMS OVER WEB</h1>
                <p style="margin: 5px 0 0; color: #0b0c0e; font-size: 14px; font-weight: 600;">Your Private Cloud Cinema Library</p>
            </div>
            <div class="body-content">
                <h2 style="margin-top: 0; color: #ffffff;">Hello {display_name},</h2>
                <p style="line-height: 1.6; color: #cbd5e1;">You have been invited as a <strong>Guest</strong> to browse and watch movies directly from Google Drive in full, uncompressed cinema quality.</p>
                
                <div style="margin: 15px 0;">
                    <span class="feature-tag">✨ Full Quality Direct Stream</span>
                    <span class="feature-tag">🚀 HEVC / H.265 Accelerated</span>
                    <span class="feature-tag">⚡ AV1 Codec Supported</span>
                    <span class="feature-tag">🍿 OTT Cinematic UI</span>
                </div>

                <div class="credential-box">
                    <div class="credential-item">Your Login Email:</div>
                    <div class="credential-value">{guest_email}</div>
                    <div style="height: 12px;"></div>
                    <div class="credential-item">Auto-Generated Temporary Password:</div>
                    <div class="credential-value">{password}</div>
                    <div style="font-size: 12px; color: #94a3b8; margin-top: 10px;">🔐 <em>You will be prompted to choose your own permanent password on first login.</em></div>
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
Temporary Password: {password}
Login URL: {login_url}

Note: You will be prompted to set your own permanent password upon first login.
Enjoy movies streamed directly from Google Drive in full quality with HEVC and AV1 support.
    """

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    return _dispatch_smtp_email(guest_email, msg, cfg, db)

def send_password_reset_email(
    user_email: str,
    user_name: Optional[str],
    temp_password: str,
    login_url: str,
    db: Optional[Session] = None
) -> Tuple[bool, str]:
    """
    Sends a new temporary password to a user who requested a password reset.
    When they log in, they will be required to change it.
    """
    cfg = get_smtp_config(db)
    sender = cfg["user"] or "drmnbot@gmail.com"
    password_smtp = (cfg["password"] or "").strip().replace(" ", "")

    if not password_smtp:
        return False, "Google App Password is not configured in SuperAdmin Settings. Please configure it to enable password reset emails."

    subject = "🔑 FilmsOverWeb Password Reset - Temporary Credentials"
    display_name = user_name if user_name else "User"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0c0e; color: #e5e7eb; margin: 0; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #14171f; border-radius: 12px; border: 1px solid #222734; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
            .header {{ background: linear-gradient(135deg, #e5a00d 0%, #c78707 100%); padding: 30px; text-align: center; }}
            .header h1 {{ margin: 0; color: #0b0c0e; font-size: 26px; font-weight: 900; letter-spacing: 1.5px; }}
            .body-content {{ padding: 30px; }}
            .credential-box {{ background: #1c212d; border-radius: 8px; border: 1px dashed #e5a00d; padding: 20px; margin: 25px 0; text-align: center; }}
            .credential-item {{ margin: 8px 0; font-size: 15px; color: #94a3b8; }}
            .credential-value {{ font-family: 'Courier New', Courier, monospace; font-size: 18px; color: #fbbf24; font-weight: bold; background: #0f172a; padding: 4px 12px; border-radius: 4px; display: inline-block; margin-top: 4px; }}
            .cta-button {{ display: inline-block; background: #e5a00d; color: #0b0c0e !important; text-decoration: none; font-weight: 900; padding: 14px 28px; border-radius: 8px; font-size: 16px; margin-top: 20px; box-shadow: 0 4px 14px rgba(229, 160, 13, 0.4); }}
            .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #64748b; border-top: 1px solid #1e2430; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>FILMS OVER WEB</h1>
                <p style="margin: 5px 0 0; color: #0b0c0e; font-size: 14px; font-weight: 600;">Password Reset Request</p>
            </div>
            <div class="body-content">
                <h2 style="margin-top: 0; color: #ffffff;">Hello {display_name},</h2>
                <p style="line-height: 1.6; color: #cbd5e1;">A password reset was requested for your FilmsOverWeb account. A new temporary password has been generated:</p>
                
                <div class="credential-box">
                    <div class="credential-item">Your Account Email:</div>
                    <div class="credential-value">{user_email}</div>
                    <div style="height: 12px;"></div>
                    <div class="credential-item">New Temporary Password:</div>
                    <div class="credential-value">{temp_password}</div>
                    <div style="font-size: 12px; color: #94a3b8; margin-top: 10px;">🔐 <em>When you log in with this temporary password, you will be prompted to set your new permanent password.</em></div>
                </div>

                <div style="text-align: center;">
                    <a href="{login_url}" class="cta-button">Sign In & Choose New Password &rarr;</a>
                </div>

                <p style="font-size: 13px; color: #94a3b8; margin-top: 30px; line-height: 1.5;">
                    🔒 <em>If you did not request this password reset, please contact your administrator.</em>
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
    msg["To"] = user_email

    text_content = f"""
Hello {display_name},

A password reset was requested for your FilmsOverWeb account.
Account Email: {user_email}
Temporary Password: {temp_password}
Login URL: {login_url}

When you sign in with this temporary password, you will be prompted to choose your own permanent password.
If you did not request this, please contact your administrator.
    """

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    return _dispatch_smtp_email(user_email, msg, cfg, db)

def _dispatch_smtp_email(to_email: str, msg: MIMEMultipart, cfg: dict, db: Optional[Session] = None) -> Tuple[bool, str]:
    sender = cfg["user"] or "drmnbot@gmail.com"
    password_smtp = (cfg["password"] or "").strip().replace(" ", "")

    def attempt_send(host: str, port: int, use_ssl: bool):
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=12) as s:
                s.login(sender, password_smtp)
                s.sendmail(sender, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=12) as s:
                s.starttls()
                s.login(sender, password_smtp)
                s.sendmail(sender, [to_email], msg.as_string())

    try:
        try:
            attempt_send(cfg["host"], cfg["port"], cfg["use_ssl"])
        except (ConnectionRefusedError, TimeoutError, OSError) as net_err:
            # Fallback to alternate standard Gmail port if connection timed out or was refused
            if "gmail.com" in cfg["host"]:
                fallback_ssl = not cfg["use_ssl"]
                fallback_port = 587 if fallback_ssl is False else 465
                print(f"[MAILER] Primary port {cfg['port']} failed ({net_err}). Attempting Gmail fallback on port {fallback_port}...")
                attempt_send(cfg["host"], fallback_port, fallback_ssl)
            else:
                raise net_err

        return True, "Email sent successfully via Gmail automation."
    except smtplib.SMTPAuthenticationError as auth_err:
        print(f"[MAILER] SMTPAuthenticationError: {auth_err}")
        return False, (
            "Gmail authentication failed (Bad Credentials). "
            "Google accounts require a 16-character Google App Password (not your standard account password). "
            "Please visit https://myaccount.google.com/apppasswords (with 2-Step Verification enabled) to generate a 16-character App Password, then paste it in SuperAdmin Settings."
        )
    except smtplib.SMTPServerDisconnected as disc_err:
        print(f"[MAILER] SMTPServerDisconnected: {disc_err}")
        return False, (
            "Gmail disconnected during authentication. "
            "Google drops the connection when a standard Google account password is used instead of a 16-character Google App Password. "
            "Please generate an App Password at https://myaccount.google.com/apppasswords and paste the 16 characters in SuperAdmin Settings."
        )
    except Exception as e:
        err_msg = str(e)
        print(f"[MAILER] Error sending email to {to_email}: {err_msg}")
        if "535" in err_msg or "BadCredentials" in err_msg or "Username and Password not accepted" in err_msg:
            return False, (
                "Gmail authentication rejected (535 Bad Credentials). "
                "Google requires a 16-character Google App Password. "
                "Please generate one at https://myaccount.google.com/apppasswords and update Settings."
            )
        return False, f"Failed to send email: {err_msg}"
