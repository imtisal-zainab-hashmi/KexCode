import functools
import os
import random
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from flask import redirect, render_template, session


def apology(message, code=400):
    """Render a message as an apology to the user."""
    def escape(s):
        for old, new in [
            ("-", "--"), (" ", "-"), ("_", "__"), ("?", "~q"),
            ("%", "~p"), ("#", "~h"), ("/", "~s"), ('"', "'"),
        ]:
            s = s.replace(old, new)
        return s
    return render_template("apology.html", top=code, bottom=escape(message)), code


def login_required(f):
    """Decorate routes to require login."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorate routes to require an admin-role user."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        if session.get("role") != "admin":
            return apology("admins only", 403)
        return f(*args, **kwargs)
    return decorated_function


def generate_code():
    """Generate a 6-digit verification code."""
    return str(random.randint(100000, 999999))


def send_verification_email(to_email, code):
    """Send a custom-styled KexCode verification email."""
    smtp_server = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("MAIL_PORT", 465))

    # Supports both your .env keys and fallback keys
    sender_email = os.environ.get("EMAIL_ADDRESS") or os.environ.get("MAIL_USERNAME")
    sender_password = os.environ.get("EMAIL_PASSWORD") or os.environ.get("MAIL_PASSWORD")

    if not sender_email or not sender_password:
        print("[WARNING] Email credentials missing in environment.")
        return False

    # Multipart container (plain text + HTML prevents spam classification)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{code} is your KexCode verification code"
    msg["From"] = formataddr(("KexCode", sender_email))
    msg["To"] = to_email
    msg["Reply-To"] = sender_email

    # Plain-text version for anti-spam scoring
    plain_text = f"""KexCode Account Verification

Welcome to KexCode!

Your verification code is: {code}

This code expires in 15 minutes.
If you did not request this code, you can safely ignore this message.
"""

    # Custom KexCode UI (Dark & Cream Monochrome)
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verify your KexCode account</title>
</head>
<body style="margin: 0; padding: 0; background-color: #080808; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e5e5e5; -webkit-font-smoothing: antialiased;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #080808; padding: 45px 15px;">
        <tr>
            <td align="center">
                <!-- Card Container -->
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 460px; background-color: #121212; border: 1px solid #252525; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 40px rgba(0, 0, 0, 0.7);">

                    <!-- Top Brand Bar -->
                    <tr>
                        <td style="padding: 28px 32px 20px 32px; border-bottom: 1px solid #1f1f1f; background: #141414;">
                            <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                                <tr>
                                    <td style="font-family: 'JetBrains Mono', Consolas, Monaco, monospace; font-size: 21px; font-weight: 800; color: #f7f4ea; letter-spacing: -0.5px;">
                                        <span style="color: #f7f4ea;">&gt;_</span> KexCode
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Body Content -->
                    <tr>
                        <td style="padding: 32px 32px 24px 32px;">
                            <div style="font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11px; font-weight: 700; letter-spacing: 0.1em; color: #f3ead6; text-transform: uppercase; margin-bottom: 8px; opacity: 0.85;">
                                SECURITY VERIFICATION
                            </div>

                            <h1 style="margin: 0 0 14px 0; font-size: 22px; font-weight: 700; color: #ffffff; letter-spacing: -0.3px;">
                                Confirm your email address
                            </h1>

                            <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 1.6; color: #a3a3a3;">
                                Welcome to KexCode. Enter this 6-digit code in the verification screen to activate your account and start coding:
                            </p>

                            <!-- Verification Code Box -->
                            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin: 24px 0;">
                                <tr>
                                    <td align="center" style="background-color: #090909; border: 1px solid #2e2e2e; border-radius: 8px; padding: 20px 24px;">
                                        <div style="font-family: 'JetBrains Mono', Consolas, Monaco, monospace; font-size: 34px; font-weight: 800; letter-spacing: 10px; color: #f7f4ea; padding-left: 10px;">
                                            {code}
                                        </div>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 20px 0 0 0; font-size: 12px; color: #737373; line-height: 1.55;">
                                ⏱️ This code will expire in <strong style="color: #999999;">15 minutes</strong>. If you did not create a KexCode account, you can safely ignore this email.
                            </p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 32px; background-color: #0c0c0c; border-top: 1px solid #1a1a1a; text-align: center;">
                            <p style="margin: 0; font-size: 11px; color: #525252; font-family: 'JetBrains Mono', Consolas, monospace;">
                                KexCode Platform &bull; Built for Coding Clubs &bull; Automated Verification
                            </p>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        if smtp_port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=12) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=12) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
        print(f"[SUCCESS] Verification email sent to {to_email}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send verification email: {e}")
        return False
