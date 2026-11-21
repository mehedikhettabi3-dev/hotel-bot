# Hotel Outreach & Application Bot

A production-ready, cloud-native bot that sends job application emails to luxury hotels worldwide (Marriott, Fairmont, Accor, Jumeirah, Four Seasons, and top Swiss/Canadian resorts). Runs 24/7 on GitHub Actions — no local PC needed.

## Features

- **Verified contacts only** — imports official recruiting addresses once; no automatic resends
- **Safe sending** — 6 emails/hour, random 20–35s intervals, ~144/day limit to protect Gmail reputation
- **Bounce protection** — DNS/MX check before sending + automatic blacklist for bounced addresses
- **Personalized emails** — hotel name and random job position inserted per email
- **Full logging** — every send attempt recorded to `logs/sent_log.jsonl`

## File Structure

```
hotel-bot/
├── bot.py                    # Core sender
├── hotel_hunter_feeder.py    # Lead manager (refill + recycle)
├── config.json               # Settings: batch size, delays, roles, contact info
├── data/
│   ├── hotels.json           # Master hotel list (200+ hotels)
│   └── blacklist.json        # Bounced addresses (never resend)
├── logs/
│   └── sent_log.jsonl        # Append-only send history
├── templates/
│   └── email_body.txt        # Email template
├── requirements.txt
└── .github/workflows/
    └── hotel_bot.yml         # GitHub Actions (hourly, 24/7)
```

## Setup

### 1. Configure your details
Edit `config.json`:
- `sender_email` — your Gmail address
- `applicant.phone` — your phone/WhatsApp number
- `positions` — the job roles you're applying for

### 2. Create a Gmail App Password
A normal Gmail password will **not** work. You must create an App Password:
1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** (requires a phone number)
3. Go to https://myaccount.google.com/apppasswords
4. Create a new app password named e.g. `HotelBot`
5. Copy the 16-character code (e.g. `abcd efgh ijkl mnop`)

### 3. Add secrets to GitHub
In your repo → **Settings → Secrets and variables → Actions**, add:
| Secret | Value |
|--------|-------|
| `GMAIL_ADDRESS` | your Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-char app password |
| `HOTEL_CV_PDF_BASE64` | Base64 of your approved PDF CV. Never commit it. Use a PDF small enough for GitHub's 48 KB secret limit (raw PDF under 36 KB). |

On a trusted Windows machine, upload the CV directly to the repository secret without displaying the encoded file:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\path\to\approved-CV.pdf')) | gh secret set HOTEL_CV_PDF_BASE64 --repo mehedikhettabi3-dev/hotel-bot
```

### 4. Enable the workflow
The bot requests an hourly schedule, but GitHub can delay or skip scheduled runs. In **Actions → Hotel Outreach Bot → Run workflow**, choose `check-smtp` (the default) to verify Gmail login without sending, or `dry-run` to preview pending applications. `send` starts a live batch on `main`.

## Running Locally (optional)

```bash
python -m pip install -r requirements.txt

# Preview what would be sent (no emails actually sent)
python bot.py --dry-run

# Refill the lead queue
python hotel_hunter_feeder.py

# Send for real (requires Gmail credentials and HOTEL_CV_PDF_BASE64)
export GMAIL_ADDRESS="you@gmail.com"          # PowerShell: $env:GMAIL_ADDRESS="..."
export GMAIL_APP_PASSWORD="abcd efgh ijkl mnop"
python bot.py --check-smtp                     # Connect and authenticate only
python bot.py
```

## Adding Hotels

Add an officially published email address to `data/verified_contacts.json` and record the hotel's careers page. The feeder imports only new addresses and preserves existing history.
```json
{"name": "Hotel Name", "email": "hr@example.com", "country": "Country", "city": "City", "position": "Kitchen Steward", "source_url": "https://example.com/careers"}
```

## Safety Notes

- Gmail free accounts allow **500 emails/day** max. This bot stays well under (~144/day) to avoid blocks.
- Sending too fast triggers a 24h account suspension. The random delays prevent this.
- Bounced addresses are blacklisted automatically and never retried.
- If you get an `AUTH ERROR`, your App Password is wrong or 2-Step Verification isn't enabled.
- For old `error` / `failed_mx` leads, verify the hotel's recruiting address and check Gmail Sent before moving any lead back to `pending`. After a `review_delivery` result, check Gmail Sent before retrying, since the server may have accepted the message.
