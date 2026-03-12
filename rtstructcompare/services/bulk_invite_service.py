import re
import secrets
import string
import smtplib
import logging
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from user.models import UserProfile, UserTypeChoices

logger = logging.getLogger(__name__)

class BulkInviteService:
    @staticmethod
    def _make_username(first_name: str, last_name: str = "") -> str:
        base = (first_name.strip() + ("." + last_name.strip() if last_name else "")).lower()
        base = re.sub(r"[^a-z0-9._]", "", base)[:30] or "user"
        username = base
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base}{counter}"
            counter += 1
        return username

    @staticmethod
    def _random_password(length: int = 12) -> str:
        alphabet = string.ascii_letters + string.digits + "!@#$%"
        while True:
            pwd = "".join(secrets.choice(alphabet) for _ in range(length))
            if (any(c.isupper() for c in pwd)
                    and any(c.islower() for c in pwd)
                    and any(c.isdigit() for c in pwd)):
                return pwd

    @classmethod
    def process_bulk_invite(cls, recipients, subject, body):
        results = []
        sent_count = 0
        skipped_count = 0
        error_count = 0
        from_email = settings.DEFAULT_FROM_EMAIL

        for item in recipients:
            first_name = item.get("first_name", "").strip()
            last_name  = item.get("last_name", "").strip()
            username   = item.get("username", "").strip()
            email_addr = item.get("email", "").strip()

            # Skip truly empty rows
            if not first_name and not email_addr:
                continue

            if User.objects.filter(email=email_addr).exists():
                results.append({
                    "name": f"{first_name} {last_name}".strip(), "email": email_addr,
                    "username": "(existing)", "status": "skipped",
                    "note": "Email already registered.",
                })
                skipped_count += 1
                continue

            try:
                # 1. Determine username
                if not username:
                    username = cls._make_username(first_name, last_name)
                
                if User.objects.filter(username=username).exists():
                    # If explicitly provided username exists, we must fail or adjust
                    # Let's auto-adjust to be safe but note it
                    original_username = username
                    username = cls._make_username(first_name, last_name) # This handles collision

                password = cls._random_password()

                # 2. Create User
                user = User.objects.create_user(
                    username=username, email=email_addr, password=password,
                    first_name=first_name, last_name=last_name
                )
                UserProfile.objects.get_or_create(user=user, defaults={"user_type": UserTypeChoices.RATER})
                
                # 3. Personalise Email
                # We use first_name for the greeting
                email_body = (
                    f"Dear {first_name},\n\n"
                    + body.replace("{name}", first_name).replace("{username}", username).replace("{password}", password)
                )

                send_mail(subject, email_body, from_email, [email_addr], fail_silently=False)
                results.append({
                    "name": f"{first_name} {last_name}".strip(), 
                    "email": email_addr, 
                    "username": username, 
                    "status": "sent", 
                    "note": "Success"
                })
                sent_count += 1
            except Exception as e:
                logger.exception("Bulk invite error for %s", email_addr)
                results.append({
                    "name": f"{first_name} {last_name}".strip(), 
                    "email": email_addr, 
                    "username": "—", 
                    "status": "error", 
                    "note": str(e)
                })
                error_count += 1

        return {
            "results": results,
            "sent_count": sent_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
        }

    @staticmethod
    def test_smtp_connection(admin_email):
        host = getattr(settings, "EMAIL_HOST", "")
        port = getattr(settings, "EMAIL_PORT", 587)
        user = getattr(settings, "EMAIL_HOST_USER", "")
        pwd  = getattr(settings, "EMAIL_HOST_PASSWORD", "")

        try:
            server = smtplib.SMTP(host, port, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, pwd)
            server.quit()
        except Exception as e:
            return False, f"SMTP Connection Failed: {str(e)}"

        try:
            send_mail(
                "[Test] SES Connection ✅",
                f"Connection to {host} is working!",
                settings.DEFAULT_FROM_EMAIL,
                [admin_email],
                fail_silently=False
            )
            return True, f"Test email sent to {admin_email}!"
        except Exception as e:
            return False, f"Auth OK but send failed: {str(e)}"
