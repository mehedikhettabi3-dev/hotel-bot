#!/usr/bin/env python3
"""Import officially published recruiting addresses without resending old leads."""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
HOTELS_FILE = DATA / "hotels.json"
VERIFIED_FILE = DATA / "verified_contacts.json"
BLACKLIST_FILE = DATA / "blacklist.json"


def load_json(path: Path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def inject_new_hotels(hotels: list, blacklist) -> int:
    seen = {hotel["email"].casefold() for hotel in hotels}
    seen.update(email.casefold() for email in blacklist)
    next_id = max((hotel.get("id", 0) for hotel in hotels), default=0) + 1
    added = 0
    for hotel in load_json(VERIFIED_FILE):
        email = hotel["email"].casefold()
        if email in seen:
            continue
        hotels.append({**hotel, "id": next_id, "status": "pending", "last_sent": None, "attempt_count": 0})
        seen.add(email)
        next_id += 1
        added += 1
    return added


def main():
    hotels = load_json(HOTELS_FILE)
    added = inject_new_hotels(hotels, load_json(BLACKLIST_FILE))
    if added:
        staging = HOTELS_FILE.with_suffix(".tmp")
        staging.write_text(json.dumps(hotels, indent=2, ensure_ascii=False), encoding="utf-8")
        staging.replace(HOTELS_FILE)
    print(f"[FEEDER] Added {added} verified addresses.")


if __name__ == "__main__":
    main()
