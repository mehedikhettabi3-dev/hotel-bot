#!/usr/bin/env python3
"""
hotel_hunter_feeder.py
Manages the hotel leads list:
- Checks if queue is running low (< threshold)
- Injects new premium hotels if needed
- Auto-recycles old unreplied leads after 14+ days
"""

import json
import os
import sys
from datetime import datetime, timedelta

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
HOTELS_FILE = os.path.join(BASE_DIR, "data", "hotels.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# ── Additional premium hotels to inject when queue runs low ───────────────────
EXTRA_HOTELS = [
    {"name": "Auberge du Soleil Napa Valley", "email": "careers@aubergeresorts.com", "country": "USA", "city": "Napa Valley", "stars": 5},
    {"name": "Meadowood Napa Valley", "email": "hr@meadowood.com", "country": "USA", "city": "Napa Valley", "stars": 5},
    {"name": "Post Ranch Inn Big Sur", "email": "careers@postranchinn.com", "country": "USA", "city": "Big Sur CA", "stars": 5},
    {"name": "Ventana Big Sur", "email": "hr@ventanabigsuyr.com", "country": "USA", "city": "Big Sur CA", "stars": 5},
    {"name": "The Lodge at Pebble Beach", "email": "careers@pebblebeach.com", "country": "USA", "city": "Pebble Beach CA", "stars": 5},
    {"name": "Four Seasons Resort Lanai", "email": "jobs.lanai@fourseasons.com", "country": "USA", "city": "Lanai Hawaii", "stars": 5},
    {"name": "Sensei Lanai A Four Seasons Resort", "email": "careers@sensei.com", "country": "USA", "city": "Lanai Hawaii", "stars": 5},
    {"name": "Grand Wailea Maui", "email": "careers@grandwailea.com", "country": "USA", "city": "Maui Hawaii", "stars": 5},
    {"name": "Four Seasons Resort Maui", "email": "jobs.maui@fourseasons.com", "country": "USA", "city": "Maui Hawaii", "stars": 5},
    {"name": "Halekulani Hotel Honolulu", "email": "hr@halekulani.com", "country": "USA", "city": "Honolulu Hawaii", "stars": 5},
    {"name": "Blackberry Farm Tennessee", "email": "careers@blackberryfarm.com", "country": "USA", "city": "Walland TN", "stars": 5},
    {"name": "Primland Resort Virginia", "email": "hr@primland.com", "country": "USA", "city": "Meadows of Dan VA", "stars": 5},
    {"name": "Montage Palmetto Bluff", "email": "careers.palmettobluff@montagehotels.com", "country": "USA", "city": "Bluffton SC", "stars": 5},
    {"name": "Cloister at Sea Island Georgia", "email": "hr@seaisland.com", "country": "USA", "city": "Sea Island GA", "stars": 5},
    {"name": "Ritz-Carlton Reynolds Lake Oconee", "email": "careers.lakeoconee@ritzcarlton.com", "country": "USA", "city": "Greensboro GA", "stars": 5},
    {"name": "Fairmont Scottsdale Princess", "email": "scottsdale.careers@fairmont.com", "country": "USA", "city": "Scottsdale AZ", "stars": 5},
    {"name": "Four Seasons Resort Scottsdale", "email": "jobs.scottsdale@fourseasons.com", "country": "USA", "city": "Scottsdale AZ", "stars": 5},
    {"name": "Enchantment Resort Sedona", "email": "hr@enchantmentresort.com", "country": "USA", "city": "Sedona AZ", "stars": 5},
    {"name": "Miraval Arizona Resort", "email": "careers@miravalresorts.com", "country": "USA", "city": "Tucson AZ", "stars": 5},
    {"name": "Amangiri Utah", "email": "careers.utah@aman.com", "country": "USA", "city": "Canyon Point UT", "stars": 5},
    {"name": "Dunton Hot Springs Colorado", "email": "hr@duntonhotsprings.com", "country": "USA", "city": "Dolores CO", "stars": 5},
    {"name": "Dunton River Camp", "email": "info@duntonhotsprings.com", "country": "USA", "city": "Dolores CO", "stars": 5},
    {"name": "Ritz-Carlton Dove Mountain Tucson", "email": "careers.dovemountain@ritzcarlton.com", "country": "USA", "city": "Marana AZ", "stars": 5},
    {"name": "Resort at Paws Up Montana", "email": "hr@pawsup.com", "country": "USA", "city": "Greenough MT", "stars": 5},
    {"name": "The Ranch at Rock Creek Montana", "email": "careers@theranchatrockcreek.com", "country": "USA", "city": "Philipsburg MT", "stars": 5},
    {"name": "Triple Creek Ranch Darby Montana", "email": "hr@triplecreekranch.com", "country": "USA", "city": "Darby MT", "stars": 5},
    {"name": "Wheatleigh Hotel Lenox MA", "email": "hr@wheatleigh.com", "country": "USA", "city": "Lenox MA", "stars": 5},
    {"name": "Blantyre Hotel Lenox MA", "email": "careers@blantyre.com", "country": "USA", "city": "Lenox MA", "stars": 5},
    {"name": "The Inn at Little Washington", "email": "hr@theinnatlittlewashington.com", "country": "USA", "city": "Washington VA", "stars": 5},
    {"name": "Fearrington House North Carolina", "email": "jobs@fearrington.com", "country": "USA", "city": "Pittsboro NC", "stars": 5},
    # New Canadian lodges
    {"name": "Clayoquot Sound Wild Canada", "email": "info@wildretreat.ca", "country": "Canada", "city": "Tofino BC", "stars": 5},
    {"name": "Fogo Island Inn Newfoundland", "email": "hr@fogoislandinn.ca", "country": "Canada", "city": "Fogo Island NL", "stars": 5},
    {"name": "Sonora Resort British Columbia", "email": "careers@sonoraresort.com", "country": "Canada", "city": "Sonora Island BC", "stars": 5},
    {"name": "April Point Lodge Quadra Island", "email": "hr@aprilpoint.com", "country": "Canada", "city": "Quadra Island BC", "stars": 4},
    {"name": "King Pacific Lodge Princess Royal Island", "email": "info@kingpacificlodge.com", "country": "Canada", "city": "Princess Royal BC", "stars": 5},
    {"name": "Nimmo Bay Wilderness Resort", "email": "info@nimmobay.com", "country": "Canada", "city": "Rivers Inlet BC", "stars": 5},
    {"name": "Trout Point Lodge Nova Scotia", "email": "hr@troutpoint.com", "country": "Canada", "city": "Kemptville NS", "stars": 4},
    {"name": "White Point Beach Resort Nova Scotia", "email": "jobs@whitepoint.com", "country": "Canada", "city": "White Point NS", "stars": 4},
    {"name": "Kingsbrae Arms Relais Chateaux", "email": "hr@kingsbraearms.com", "country": "Canada", "city": "St Andrews NB", "stars": 5},
    {"name": "Hastings House Country Estate", "email": "hr@hastingshouse.com", "country": "Canada", "city": "Salt Spring Island BC", "stars": 5},
    # More European luxury
    {"name": "Domaine des Hauts de Loire", "email": "hr@domainehautsloire.com", "country": "France", "city": "Loire Valley", "stars": 5},
    {"name": "Chateau de Bagnols Lyon", "email": "careers@chateaudebagnols.com", "country": "France", "city": "Beaujolais", "stars": 5},
    {"name": "Villa La Coste Provence", "email": "hr@villalacoste.com", "country": "France", "city": "Provence", "stars": 5},
    {"name": "Le Mas de Pierre Saint-Paul-de-Vence", "email": "rh@lemasdepierre.com", "country": "France", "city": "Saint-Paul-de-Vence", "stars": 5},
    {"name": "Hotel du Cap-Eden-Roc Antibes", "email": "rh@oetkercollection.com", "country": "France", "city": "Antibes", "stars": 5},
    {"name": "Grand-Hotel du Cap-Ferrat", "email": "careers.capferrat@fourseasons.com", "country": "France", "city": "Cap-Ferrat", "stars": 5},
    {"name": "Villa Ephrussi de Rothschild", "email": "hr@villa-ephrussi.com", "country": "France", "city": "Cap-Ferrat", "stars": 5},
    {"name": "Chateau Saint-Martin & Spa", "email": "rh@chateau-st-martin.com", "country": "France", "city": "Vence", "stars": 5},
    {"name": "Terre Blanche Hotel Tourrettes", "email": "rh@terre-blanche.com", "country": "France", "city": "Tourrettes", "stars": 5},
    {"name": "La Bastide de Gordes", "email": "hr@bastide-de-gordes.com", "country": "France", "city": "Gordes", "stars": 5},
    # Middle East expansion
    {"name": "Six Senses Zighy Bay Oman", "email": "careers.zighy@sixsenses.com", "country": "Oman", "city": "Musandam", "stars": 5},
    {"name": "The Chedi Muscat", "email": "careers.muscat@ghmhotels.com", "country": "Oman", "city": "Muscat", "stars": 5},
    {"name": "Alila Jabal Akhdar Oman", "email": "careers@alilahotels.com", "country": "Oman", "city": "Jabal Akhdar", "stars": 5},
    {"name": "Jumeirah Al Naseem Dubai", "email": "alnaseem.careers@jumeirah.com", "country": "UAE", "city": "Dubai", "stars": 5},
    {"name": "Jumeirah Al Qasr Dubai", "email": "alqasr.careers@jumeirah.com", "country": "UAE", "city": "Dubai", "stars": 5},
    {"name": "Address Downtown Dubai", "email": "careers@addresshotels.com", "country": "UAE", "city": "Dubai", "stars": 5},
    {"name": "FIVE Palm Jumeirah Dubai", "email": "hr@fivehotelsandresorts.com", "country": "UAE", "city": "Dubai", "stars": 5},
    {"name": "Bulgari Resort Dubai", "email": "hr@bulgarihotels.com", "country": "UAE", "city": "Dubai", "stars": 5},
    {"name": "Atlantis The Royal Dubai", "email": "careers@atlantistheroyal.com", "country": "UAE", "city": "Dubai", "stars": 5},
    {"name": "Caesars Palace Bluewaters Dubai", "email": "careers@caesarspalace.ae", "country": "UAE", "city": "Dubai", "stars": 5},
]


def load_json(path: str) -> list | dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_next_id(hotels: list) -> int:
    return max((h.get("id", 0) for h in hotels), default=0) + 1


def recycle_old_leads(hotels: list, recycle_after_days: int) -> int:
    """Reset status to 'pending' for hotels sent > recycle_after_days ago with no reply."""
    cutoff = datetime.utcnow() - timedelta(days=recycle_after_days)
    recycled = 0
    for hotel in hotels:
        if hotel.get("status") == "sent" and hotel.get("last_sent"):
            try:
                last = datetime.fromisoformat(hotel["last_sent"])
                if last < cutoff:
                    hotel["status"] = "pending"
                    recycled += 1
            except ValueError:
                pass
    return recycled


def inject_new_hotels(hotels: list, blacklist: list) -> int:
    """Add hotels from EXTRA_HOTELS that are not already in the list or blacklist."""
    existing_emails = {h["email"].lower() for h in hotels}
    blacklisted    = {b.lower() for b in blacklist}
    next_id = get_next_id(hotels)
    added = 0
    for h in EXTRA_HOTELS:
        email = h["email"].lower()
        if email not in existing_emails and email not in blacklisted:
            hotels.append({
                "id": next_id,
                "name": h["name"],
                "email": h["email"],
                "country": h["country"],
                "city": h["city"],
                "stars": h["stars"],
                "status": "pending",
                "last_sent": None,
                "attempt_count": 0,
            })
            existing_emails.add(email)
            next_id += 1
            added += 1
    return added


def main():
    # Load config
    config = load_json(CONFIG_FILE)
    threshold      = config.get("low_queue_threshold", 15)
    recycle_days   = config.get("recycle_after_days", 14)

    # Load data
    hotels_path    = HOTELS_FILE
    blacklist_path = os.path.join(BASE_DIR, "data", "blacklist.json")
    hotels         = load_json(hotels_path)
    blacklist      = load_json(blacklist_path)

    print(f"[FEEDER] Total hotels in DB: {len(hotels)}")

    # Step 1 — Recycle old unreplied leads
    recycled = recycle_old_leads(hotels, recycle_days)
    if recycled:
        print(f"[FEEDER] Recycled {recycled} old leads back to 'pending'")

    # Step 2 — Count pending
    pending = [h for h in hotels if h.get("status") == "pending"]
    print(f"[FEEDER] Pending in queue: {len(pending)}")

    # Step 3 — Inject new hotels if queue is low
    if len(pending) < threshold:
        print(f"[FEEDER] Queue low (< {threshold}). Injecting new hotels...")
        added = inject_new_hotels(hotels, blacklist)
        print(f"[FEEDER] Injected {added} new hotels. Total now: {len(hotels)}")
    else:
        print(f"[FEEDER] Queue healthy. No injection needed.")

    # Save updated list
    save_json(hotels_path, hotels)
    print("[FEEDER] hotels.json saved successfully.")


if __name__ == "__main__":
    main()
