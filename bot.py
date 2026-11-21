#!/usr/bin/env python3
"""
bot.py
Core Hotel Outreach Bot — reads the queue, sends emails, logs results.
Designed to run safely via GitHub Actions (cloud) every hour.
"""

import json
import os
import sys
import random
import time
import smtplib
import ssl
import argparse
import base64
import binascii
from contextlib import suppress
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from hotel_hunter_feeder import inject_new_hotels

import dns.exception
import dns.resolver
import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
HOTELS_FILE     = os.path.join(BASE_DIR, "data", "hotels.json")
BLACKLIST_FILE  = os.path.join(BASE_DIR, "data", "blacklist.json")
LOG_FILE        = os.path.join(BASE_DIR, "logs", "sent_log.jsonl")
CONFIG_FILE     = os.path.join(BASE_DIR, "config.json")
TEMPLATE_FILE   = os.path.join(BASE_DIR, "templates", "email_body.txt")


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def append_log(entry: dict) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def check_mx(domain: str, timeout: int = 5) -> bool | None:
    """True for a mail route, False for no route, None for a temporary DNS failure."""
    try:
        records = dns.resolver.resolve(domain, "MX", lifetime=timeout)
        return any(str(record.exchange) != "." for record in records)
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        # SMTP falls back to the domain's address only when there is no MX.
        temporary_failure = False
        for record_type in ("A", "AAAA"):
            try:
                return bool(dns.resolver.resolve(domain, record_type, lifetime=timeout))
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                continue
            except dns.exception.DNSException:
                temporary_failure = True
        return None if temporary_failure else False
    except dns.exception.DNSException:
        return None


def build_email(template: str, hotel: dict, config: dict) -> tuple[str, str]:
    """Return (subject, body) personalised for this hotel."""
    position = hotel.get("position") or random.choice(config.get("positions", ["Kitchen Steward"]))
    applicant = config.get("applicant", {})

    body = template.replace("{hotel_name}", hotel["name"])
    body = body.replace("{position}", position)
    body = body.replace("{phone}", applicant.get("phone", ""))
    body = body.replace("{sender_email}", config.get("sender_email", ""))

    subject = hotel.get("subject_template", "Application for {position} - {hotel}").format(
        position=position, hotel=hotel["name"], name=applicant.get("name", "Applicant"))
    return subject, body


def connect_gmail(sender: str, password: str):
    """Open and authenticate a certificate-verified SMTP connection."""
    server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30,
                             context=ssl.create_default_context())
    try:
        server.login(sender, password)
    except (smtplib.SMTPException, OSError):
        with suppress(OSError):
            server.close()
        raise
    return server


class DeliveryUncertain(Exception):
    """SMTP connection dropped while submitting; retrying may duplicate mail."""


class GmailAPIError(Exception):
    """Configuration or an explicit API rejection; nothing was submitted."""


def gmail_api_token():
    fields = {key: os.environ.get(f"GMAIL_OAUTH_{key.upper()}", "").strip()
              for key in ("client_id", "client_secret", "refresh_token")}
    if not all(fields.values()):
        raise GmailAPIError("Configure GMAIL_OAUTH_CLIENT_ID, GMAIL_OAUTH_CLIENT_SECRET and GMAIL_OAUTH_REFRESH_TOKEN.")
    try:
        response = requests.post("https://oauth2.googleapis.com/token",
                                 data={**fields, "grant_type": "refresh_token"}, timeout=20,
                                 allow_redirects=False)
        if response.status_code != 200:
            raise GmailAPIError(f"Google OAuth token exchange failed (HTTP {response.status_code}).")
        token = response.json().get("access_token")
    except (requests.RequestException, ValueError) as exc:
        raise GmailAPIError("Google OAuth token exchange could not be completed.") from exc
    if not token:
        raise GmailAPIError("Google OAuth response did not contain an access token.")
    return token


def send_via_gmail_api(message, token):
    try:
        response = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")},
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise DeliveryUncertain from exc
    if response.status_code >= 500 or response.status_code == 408:
        raise DeliveryUncertain
    if response.status_code != 200:
        raise GmailAPIError(f"Gmail API rejected the send (HTTP {response.status_code}).")


def send_email(sender: str, password: str,
               recipient: str, subject: str, body: str, cv: bytes | None = None,
               api_token: str | None = None) -> None:
    msg = MIMEMultipart()
    msg["From"]    = sender
    msg["To"]      = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if cv:
        attachment = MIMEApplication(cv, _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename="CV.pdf")
        msg.attach(attachment)

    if api_token:
        send_via_gmail_api(msg, api_token)
        return
    server = connect_gmail(sender, password)
    try:
        server.sendmail(sender, recipient, msg.as_string())
    except smtplib.SMTPServerDisconnected as exc:
        raise DeliveryUncertain from exc
    except smtplib.SMTPException:
        raise  # A definite SMTP rejection isn't an uncertain delivery.
    except OSError as exc:
        raise DeliveryUncertain from exc
    finally:
        # A disconnect during cleanup must not negate Gmail's acceptance.
        with suppress(OSError):
            server.close()


# ── Main ───────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False, check_smtp: bool = False, check_api: bool = False):
    # Load config
    config = load_json(CONFIG_FILE)

    sender_email  = (os.environ.get("GMAIL_ADDRESS") or config.get("sender_email", "")).strip()
    sender_pass   = "".join(os.environ.get("GMAIL_APP_PASSWORD", "").split())
    batch_size    = config.get("batch_size",  6)
    delay_min     = config.get("delay_min",  20)
    delay_max     = config.get("delay_max",  35)
    daily_limit   = config.get("daily_limit", 144)

    if not sender_email:
        print("[BOT] ERROR: sender_email not set in config.json or GMAIL_ADDRESS env var.")
        sys.exit(1)
    use_api = check_api or (not check_smtp and os.environ.get("HOTEL_MAIL_TRANSPORT") == "gmail-api")
    if not sender_pass and not dry_run and not use_api:
        print("[BOT] ERROR: GMAIL_APP_PASSWORD env var is not set.")
        sys.exit(1)

    if check_smtp:
        try:
            server = connect_gmail(sender_email, sender_pass)
        except smtplib.SMTPAuthenticationError as exc:
            sys.exit(f"[BOT] AUTH ERROR ({exc.smtp_code}): check the Gmail App Password and account.")
        except (smtplib.SMTPException, OSError) as exc:
            sys.exit(f"[BOT] SMTP connection failed on port 465 ({type(exc).__name__}). No email sent.")
        with suppress(OSError):
            server.close()
        print("[BOT] Gmail SMTP authentication succeeded. No email sent.")
        return

    if check_api:
        try:
            gmail_api_token()
        except GmailAPIError as exc:
            sys.exit(f"[BOT] {exc} No email sent.")
        print("[BOT] Gmail OAuth token refreshed successfully. No email sent.")
        return

    # Load data
    hotels    = load_json(HOTELS_FILE)
    blacklist = set(b.lower() for b in load_json(BLACKLIST_FILE))
    if dry_run:
        inject_new_hotels(hotels, blacklist)
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as file:
        template = file.read()

    # Count already sent today (based on log)
    sent_today = 0
    today_str  = datetime.utcnow().strftime("%Y-%m-%d")
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("timestamp", "").startswith(today_str) and entry.get("status") == "sent":
                        sent_today += 1
                except Exception:
                    pass

    remaining_today = daily_limit - sent_today
    if remaining_today <= 0:
        print(f"[BOT] Daily limit of {daily_limit} already reached. Stopping.")
        return

    actual_batch = min(batch_size, remaining_today)
    print(f"[BOT] Sent today: {sent_today} / {daily_limit}. Will send up to {actual_batch} now.")

    # Build queue — pending hotels not blacklisted
    queue = [
        h for h in hotels
        if h.get("status") == "pending"
        and h.get("source_url")
        and h.get("email", "").lower() not in blacklist
    ]

    if not queue:
        print("[BOT] No new verified recruiting addresses in queue.")
        return

    cv = None
    api_token = None
    if not dry_run:
        try:
            cv = base64.b64decode(os.environ.get("HOTEL_CV_PDF_BASE64", "").strip(), validate=True)
        except binascii.Error:
            sys.exit("[BOT] HOTEL_CV_PDF_BASE64 is not valid base64. No email sent.")
        if not cv.startswith(b"%PDF-"):
            sys.exit("[BOT] Set HOTEL_CV_PDF_BASE64 to your approved PDF CV. No email sent.")
        if use_api:
            try:
                api_token = gmail_api_token()
            except GmailAPIError as exc:
                sys.exit(f"[BOT] {exc} No email sent.")

    print(f"[BOT] Pending hotels available: {len(queue)}")

    sent_count = 0
    for hotel in queue[:actual_batch]:
        email_addr = hotel["email"]
        domain     = email_addr.split("@")[-1]
        now        = datetime.utcnow().isoformat()

        # MX check — skip dead domains to reduce bounces (skipped in dry-run)
        mail_route = True if dry_run else check_mx(domain)
        if mail_route is None:
            print(f"[BOT] Temporary DNS error for {domain}; leaving lead pending.")
            continue
        if not mail_route:
            print(f"[BOT] SKIP (no MX) → {email_addr}")
            log_entry = {
                "timestamp": now,
                "hotel": hotel["name"],
                "email": email_addr,
                "status": "skipped_no_mx",
                "error": "DNS/MX check failed"
            }
            append_log(log_entry)
            # Mark as failed so we don't keep retrying
            hotel["status"] = "failed_mx"
            save_json(HOTELS_FILE, hotels)
            continue

        subject, body = build_email(template, hotel, {**config, "sender_email": sender_email})

        if dry_run:
            print(f"[DRY-RUN] Would send to: {email_addr} | Subject: {subject}")
            sent_count += 1
            continue
        else:
            try:
                send_email(
                    sender=sender_email,
                    password=sender_pass,
                    recipient=email_addr,
                    subject=subject,
                    body=body + "\n\nPlease find my CV attached.",
                    cv=cv,
                    api_token=api_token,
                )
                print(f"[BOT] SENT ✓ → {hotel['name']} <{email_addr}>")
                log_entry = {
                    "timestamp": now,
                    "hotel": hotel["name"],
                    "email": email_addr,
                    "country": hotel.get("country", ""),
                    "status": "sent",
                    "subject": subject
                }
                hotel["status"]        = "sent"
                hotel["last_sent"]     = now
                hotel["attempt_count"] = hotel.get("attempt_count", 0) + 1
                sent_count += 1

            except smtplib.SMTPAuthenticationError as e:
                print(f"[BOT] AUTH ERROR ({e.smtp_code}) — check App Password.")
                log_entry = {
                    "timestamp": now,
                    "hotel": hotel["name"],
                    "email": email_addr,
                    "status": "auth_error",
                    "error": f"SMTP {e.smtp_code}"
                }
                append_log(log_entry)
                save_json(HOTELS_FILE, hotels)
                sys.exit(1)   # stop the run — no point continuing with bad creds

            except smtplib.SMTPRecipientsRefused as e:
                code = e.recipients.get(email_addr, (0, b""))[0]
                if not 500 <= code < 600:
                    sys.exit(f"[BOT] Recipient temporarily refused (SMTP {code}); lead remains pending.")
                print(f"[BOT] BOUNCE → {email_addr} (recipient refused)")
                log_entry = {
                    "timestamp": now,
                    "hotel": hotel["name"],
                    "email": email_addr,
                    "status": "bounced",
                    "error": str(e)
                }
                hotel["status"] = "bounced"
                # Add to blacklist so we never retry
                blacklist_data = load_json(BLACKLIST_FILE)
                if email_addr.lower() not in [b.lower() for b in blacklist_data]:
                    blacklist_data.append(email_addr)
                    save_json(BLACKLIST_FILE, blacklist_data)

            except DeliveryUncertain:
                hotel["status"] = "review_delivery"
                save_json(HOTELS_FILE, hotels)
                append_log({
                    "timestamp": now,
                    "hotel": hotel["name"],
                    "email": email_addr,
                    "status": "review_delivery",
                    "error": "Delivery unconfirmed; check Gmail Sent before retrying."
                })
                sys.exit("[BOT] Delivery uncertain; check Gmail Sent before retrying this lead.")

            except (smtplib.SMTPException, OSError) as e:
                sys.exit(f"[BOT] SMTP failure ({type(e).__name__}); lead remains pending.")
            except GmailAPIError as exc:
                sys.exit(f"[BOT] {exc} Lead remains pending.")

            append_log(log_entry)

        # Save after each send so no progress is lost on crash
        save_json(HOTELS_FILE, hotels)

        # Random delay between sends to mimic human behaviour (skipped in dry-run)
        if not dry_run and sent_count < actual_batch:
            delay = random.randint(delay_min, delay_max)
            print(f"[BOT] Waiting {delay}s before next send...")
            time.sleep(delay)

    action = "Previewed" if dry_run else "Sent"
    print(f"\n[BOT] Session complete. {action} {sent_count} email(s) this run.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hotel Outreach Bot")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                        help="Simulate sending without actually sending emails")
    mode.add_argument("--check-smtp", action="store_true",
                      help="Check Gmail connectivity and login without sending email")
    mode.add_argument("--check-api", action="store_true",
                      help="Refresh the Google OAuth token without sending email")
    args = parser.parse_args()
    main(dry_run=args.dry_run, check_smtp=args.check_smtp, check_api=args.check_api)
