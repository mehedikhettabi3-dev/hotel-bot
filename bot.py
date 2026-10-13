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
import socket
import argparse
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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


def check_mx(domain: str, timeout: int = 5) -> bool:
    """Quick DNS check — confirm the domain has an MX record (can receive mail)."""
    try:
        socket.setdefaulttimeout(timeout)
        results = socket.getaddrinfo(domain, None)
        return len(results) > 0
    except Exception:
        return False


def build_email(template: str, hotel: dict, config: dict) -> tuple[str, str]:
    """Return (subject, body) personalised for this hotel."""
    position = random.choice(config.get("positions", ["Kitchen Steward"]))
    applicant = config.get("applicant", {})

    body = template.replace("{hotel_name}", hotel["name"])
    body = body.replace("{position}", position)
    body = body.replace("{phone}", applicant.get("phone", ""))
    body = body.replace("{sender_email}", config.get("sender_email", ""))

    subject = f"Application for {position} - {hotel['name']}"
    return subject, body


def send_email(smtp_host: str, smtp_port: int,
               sender: str, password: str,
               recipient: str, subject: str, body: str) -> None:
    """Send a single email via Gmail SMTP TLS."""
    msg = MIMEMultipart("alternative")
    msg["From"]    = sender
    msg["To"]      = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())


# ── Main ───────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False):
    # Load config
    config = load_json(CONFIG_FILE)

    sender_email  = os.environ.get("GMAIL_ADDRESS",      config.get("sender_email", ""))
    sender_pass   = os.environ.get("GMAIL_APP_PASSWORD", "")
    batch_size    = config.get("batch_size",  6)
    delay_min     = config.get("delay_min",  20)
    delay_max     = config.get("delay_max",  35)
    daily_limit   = config.get("daily_limit", 144)

    if not sender_email:
        print("[BOT] ERROR: sender_email not set in config.json or GMAIL_ADDRESS env var.")
        sys.exit(1)
    if not sender_pass and not dry_run:
        print("[BOT] ERROR: GMAIL_APP_PASSWORD env var is not set.")
        sys.exit(1)

    # Load data
    hotels    = load_json(HOTELS_FILE)
    blacklist = set(b.lower() for b in load_json(BLACKLIST_FILE))
    template  = open(TEMPLATE_FILE, "r", encoding="utf-8").read()

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
        and h.get("email", "").lower() not in blacklist
    ]

    if not queue:
        print("[BOT] Queue is empty. Run hotel_hunter_feeder.py to refill.")
        return

    print(f"[BOT] Pending hotels available: {len(queue)}")

    sent_count = 0
    for hotel in queue[:actual_batch]:
        email_addr = hotel["email"]
        domain     = email_addr.split("@")[-1]
        now        = datetime.utcnow().isoformat()

        # MX check — skip dead domains to reduce bounces (skipped in dry-run)
        if not dry_run and not check_mx(domain):
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
            continue

        subject, body = build_email(template, hotel, config)

        if dry_run:
            print(f"[DRY-RUN] Would send to: {email_addr} | Subject: {subject}")
            log_entry = {
                "timestamp": now,
                "hotel": hotel["name"],
                "email": email_addr,
                "status": "dry_run",
                "subject": subject
            }
            append_log(log_entry)
            hotel["status"]        = "pending"   # keep pending in dry-run
            sent_count += 1
        else:
            try:
                send_email(
                    smtp_host="smtp.gmail.com",
                    smtp_port=587,
                    sender=sender_email,
                    password=sender_pass,
                    recipient=email_addr,
                    subject=subject,
                    body=body
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
                print(f"[BOT] AUTH ERROR — check App Password. Details: {e}")
                log_entry = {
                    "timestamp": now,
                    "hotel": hotel["name"],
                    "email": email_addr,
                    "status": "auth_error",
                    "error": str(e)
                }
                append_log(log_entry)
                save_json(HOTELS_FILE, hotels)
                sys.exit(1)   # stop the run — no point continuing with bad creds

            except smtplib.SMTPRecipientsRefused as e:
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

            except Exception as e:
                print(f"[BOT] ERROR → {hotel['name']} ({email_addr}): {e}")
                log_entry = {
                    "timestamp": now,
                    "hotel": hotel["name"],
                    "email": email_addr,
                    "status": "error",
                    "error": str(e)
                }
                hotel["status"] = "error"

            append_log(log_entry)

        # Save after each send so no progress is lost on crash
        save_json(HOTELS_FILE, hotels)

        # Random delay between sends to mimic human behaviour (skipped in dry-run)
        if not dry_run and sent_count < actual_batch:
            delay = random.randint(delay_min, delay_max)
            print(f"[BOT] Waiting {delay}s before next send...")
            time.sleep(delay)

    print(f"\n[BOT] Session complete. Sent {sent_count} email(s) this run.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hotel Outreach Bot")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate sending without actually sending emails")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
