import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Target States: NC and neighboring states (VA, SC, TN, GA)
TARGET_STATES = ["NC", "VA", "SC", "TN", "GA", "NORTH CAROLINA", "VIRGINIA", "SOUTH CAROLINA", "TENNESSEE", "GEORGIA"]
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
SEEN_FILE = "seen_commissions.json"

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen(seen_ids):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen_ids), f, indent=2)

def fetch_raleigh_arts():
    url = "https://raleighnc.gov/arts/services/artist-calls"
    opportunities = []
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)
                href = a["href"]
                if any(k in href.lower() for k in ["artist-call", "public-art", "seek-raleigh"]):
                    full_url = href if href.startswith("http") else f"https://raleighnc.gov{href}"
                    if len(title) > 5 and title not in ["Public Art", "Artist Calls", "Learn More"]:
                        opportunities.append({
                            "id": full_url,
                            "title": title,
                            "organization": "City of Raleigh Arts",
                            "location": "Raleigh, NC",
                            "state": "NC",
                            "url": full_url,
                            "budget": "Varies by project",
                            "category": "Municipal Public Art"
                        })
    except Exception as e:
        print(f"Error fetching Raleigh Arts: {e}")
    return opportunities

def fetch_durham_arts():
    url = "https://www.durhamnc.gov/2984/Durham-Calls-for-Artists"
    opportunities = []
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)
                href = a["href"]
                if "call" in href.lower() or "rfq" in href.lower() or "public-art" in href.lower():
                    full_url = href if href.startswith("http") else f"https://www.durhamnc.gov{href}"
                    if len(title) > 8 and "durham" in title.lower():
                        opportunities.append({
                            "id": full_url,
                            "title": title,
                            "organization": "City/County of Durham",
                            "location": "Durham, NC",
                            "state": "NC",
                            "url": full_url,
                            "budget": "Varies",
                            "category": "Municipal Public Art"
                        })
    except Exception as e:
        print(f"Error fetching Durham Arts: {e}")
    return opportunities

def fetch_triangle_artworks():
    url = "https://www.triangleartworks.org/calls-for-artists"
    opportunities = []
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)
                href = a["href"]
                if len(title) > 10 and any(kw in title.lower() for kw in ["public art", "mural", "rfq", "commission", "call"]):
                    full_url = href if href.startswith("http") else f"https://www.triangleartworks.org{href}"
                    opportunities.append({
                        "id": full_url,
                        "title": title,
                        "organization": "Triangle ArtWorks Aggregator",
                        "location": "Raleigh / Durham / Chapel Hill, NC",
                        "state": "NC",
                        "url": full_url,
                        "budget": "See opportunity details",
                        "category": "Regional Call"
                    })
    except Exception as e:
        print(f"Error fetching Triangle ArtWorks: {e}")
    return opportunities

def fetch_nc_arts_council():
    url = "https://www.ncarts.org/grants-resources/resources/artists/artist-opportunities"
    opportunities = []
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)
                href = a["href"]
                if any(kw in title.lower() for kw in ["public art", "commission", "sculpture", "mural", "rfq"]):
                    full_url = href if href.startswith("http") else f"https://www.ncarts.org{href}"
                    opportunities.append({
                        "id": full_url,
                        "title": title,
                        "organization": "North Carolina Arts Council",
                        "location": "North Carolina (Statewide)",
                        "state": "NC",
                        "url": full_url,
                        "budget": "State / Regional Grant or Commission",
                        "category": "Statewide Call"
                    })
    except Exception as e:
        print(f"Error fetching NC Arts Council: {e}")
    return opportunities

def send_discord_webhook(new_items):
    if not DISCORD_WEBHOOK_URL:
        print("No DISCORD_WEBHOOK_URL environment variable set. Skipping Discord post.")
        return

    embeds = []
    for item in new_items[:10]:
        embed = {
            "title": item["title"][:256],
            "url": item["url"],
            "color": 0x3498DB if item["state"] == "NC" else 0x9B59B6,
            "fields": [
                {"name": "🏛️ Organization", "value": item["organization"], "inline": True},
                {"name": "📍 Location", "value": f"{item['location']} ({item['state']})", "inline": True},
                {"name": "💰 Budget / Notes", "value": item["budget"], "inline": False}
            ],
            "footer": {"text": f"Category: {item['category']} | Scanned for Jen"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        embeds.append(embed)

    payload = {
        "username": "Public Art Commission Tracker",
        "avatar_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a2/Arts_icon.svg/512px-Arts_icon.svg.png",
        "content": f"🎨 **Daily Public Art Commission Update for Jen**\nFound **{len(new_items)}** new opportunity/opportunities in NC and neighboring states!",
        "embeds": embeds
    }

    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if res.status_code in [200, 204]:
            print("Successfully posted daily update to Discord!")
        else:
            print(f"Discord Webhook status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"Error sending Discord Webhook: {e}")

def main():
    print(f"[{datetime.now().isoformat()}] Starting Public Art Commission Scan...")
    seen_ids = load_seen()
    all_opportunities = []

    all_opportunities.extend(fetch_raleigh_arts())
    all_opportunities.extend(fetch_durham_arts())
    all_opportunities.extend(fetch_triangle_artworks())
    all_opportunities.extend(fetch_nc_arts_council())

    new_opportunities = [item for item in all_opportunities if item["id"] not in seen_ids]

    print(f"Total fetched: {len(all_opportunities)} | New items: {len(new_opportunities)}")

    if new_opportunities:
        send_discord_webhook(new_opportunities)
        for item in new_opportunities:
            seen_ids.add(item["id"])
        save_seen(seen_ids)
    else:
        print("No new opportunities found today.")

if __name__ == "__main__":
    main()
