import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Target States: NC and neighboring states (VA, SC, TN, GA)
TARGET_STATES = ["NC", "VA", "SC", "TN", "GA", "NORTH CAROLINA", "VIRGINIA", "SOUTH CAROLINA", "TENNESSEE", "GEORGIA"]
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
SEEN_FILE = "seen_commissions.json"

# Generic nav/share links that sometimes match our keyword filters but aren't real opportunities
NON_OPPORTUNITY_TITLES = {
    "twitter", "facebook", "instagram", "linkedin", "share", "email", "print",
    "tweet", "pinterest", "youtube", "x", "learn more", "public art", "artist calls"
}

BUDGET_PATTERN = re.compile(r'\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?(?:\s*-\s*\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)?')

DATE_PATTERN = re.compile(
    r'(?:(?:January|February|March|April|May|June|July|August|September|October|November|December|'
    r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}'
    r'|\d{1,2}/\d{1,2}/\d{2,4}'
    r'|\d{4}-\d{2}-\d{2})',
    re.IGNORECASE
)

BUDGET_KEYWORDS = ["budget", "stipend", "honorarium", "compensation", "commission fee", "award amount", "total budget", "project budget"]
DEADLINE_KEYWORDS = ["deadline", "due date", "due by", "apply by", "applications due", "submissions due", "postmark", "submission deadline", "must be received"]


def fetch_opportunity_details(url):
    """Fetch an individual opportunity's page and pull out a summary, budget, and due date."""
    details = {"summary": "No summary available.", "budget": "Not specified", "due_date": "Not specified"}
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.status_code != 200:
            return details
        soup = BeautifulSoup(res.text, "html.parser")

        meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        summary = meta_desc["content"].strip() if meta_desc and meta_desc.get("content") else ""
        if not summary:
            for p in soup.find_all("p"):
                text = p.get_text(strip=True)
                lower = text.lower()
                if (len(text) > 120
                        and "thank you for printing this page" not in lower
                        and "non-discrimination policy" not in lower
                        and not lower.startswith("updated:")):
                    summary = text
                    break
        if summary:
            details["summary"] = (summary[:280] + "…") if len(summary) > 280 else summary

        page_text = soup.get_text(" ", strip=True)
        lower_text = page_text.lower()

        for keyword in BUDGET_KEYWORDS:
            idx = lower_text.find(keyword)
            if idx != -1:
                window = page_text[max(0, idx - 60):idx + 150]
                match = BUDGET_PATTERN.search(window)
                if match:
                    details["budget"] = match.group(0)
                    break
        if details["budget"] == "Not specified":
            match = BUDGET_PATTERN.search(page_text)
            if match:
                details["budget"] = match.group(0)

        for keyword in DEADLINE_KEYWORDS:
            idx = lower_text.find(keyword)
            if idx != -1:
                window = page_text[max(0, idx - 60):idx + 100]
                match = DATE_PATTERN.search(window)
                if match:
                    details["due_date"] = match.group(0)
                    break
    except Exception as e:
        print(f"Error fetching details for {url}: {e}")
    return details

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
                if not (href.startswith("/") or "raleighnc.gov" in href.lower()):
                    continue
                if any(k in href.lower() for k in ["artist-call", "public-art", "seek-raleigh"]):
                    full_url = href if href.startswith("http") else f"https://raleighnc.gov{href}"
                    if len(title) > 5 and title.lower() not in NON_OPPORTUNITY_TITLES:
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
                if not (href.startswith("/") or "durhamnc.gov" in href.lower()):
                    continue
                if "customer survey" in title.lower() or "one call" in title.lower():
                    continue
                if "rfq" in href.lower() or "public-art" in href.lower() or "call-for" in href.lower() or "calls-for" in href.lower():
                    full_url = href if href.startswith("http") else f"https://www.durhamnc.gov{href}"
                    if full_url.rstrip("/") == url.rstrip("/"):
                        continue
                    if len(title) > 8 and "durham" in title.lower() and title.lower() not in NON_OPPORTUNITY_TITLES:
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
                if title.lower() in NON_OPPORTUNITY_TITLES:
                    continue
                if len(title) > 10 and any(kw in title.lower() for kw in ["public art", "mural", "rfq", "commission", "call for", "calls for"]):
                    full_url = href if href.startswith("http") else f"https://www.triangleartworks.org{href}"
                    if full_url.rstrip("/") == url.rstrip("/"):
                        continue
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
                if title.lower() in NON_OPPORTUNITY_TITLES:
                    continue
                if any(kw in title.lower() for kw in ["public art", "commission", "sculpture", "mural", "rfq"]):
                    full_url = href if href.startswith("http") else f"https://www.ncarts.org{href}"
                    if full_url.rstrip("/") == url.rstrip("/"):
                        continue
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

DISCORD_EMBEDS_PER_MESSAGE = 10

def build_embed(item):
    details = fetch_opportunity_details(item["url"])
    time.sleep(1)  # be polite to the source sites between detail-page fetches
    return {
        "title": item["title"][:256],
        "url": item["url"],
        "description": details["summary"][:2048],
        "color": 0x3498DB if item["state"] == "NC" else 0x9B59B6,
        "fields": [
            {"name": "🏛️ Organization", "value": item["organization"], "inline": True},
            {"name": "📍 Location", "value": f"{item['location']} ({item['state']})", "inline": True},
            {"name": "💰 Budget", "value": details["budget"], "inline": True},
            {"name": "📅 Due Date", "value": details["due_date"], "inline": True}
        ],
        "footer": {"text": f"Category: {item['category']} | Scanned for Jen"},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

def send_discord_webhook(new_items):
    if not DISCORD_WEBHOOK_URL:
        print("No DISCORD_WEBHOOK_URL environment variable set. Skipping Discord post.")
        return

    chunks = [new_items[i:i + DISCORD_EMBEDS_PER_MESSAGE] for i in range(0, len(new_items), DISCORD_EMBEDS_PER_MESSAGE)]

    for chunk_index, chunk in enumerate(chunks):
        embeds = [build_embed(item) for item in chunk]

        if len(chunks) > 1:
            header = f"🎨 **Daily Public Art Commission Update for Jen** (part {chunk_index + 1}/{len(chunks)})\nFound **{len(new_items)}** new opportunity/opportunities in NC and neighboring states!"
        else:
            header = f"🎨 **Daily Public Art Commission Update for Jen**\nFound **{len(new_items)}** new opportunity/opportunities in NC and neighboring states!"

        payload = {
            "username": "Public Art Commission Tracker",
            "avatar_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a2/Arts_icon.svg/512px-Arts_icon.svg.png",
            "content": header,
            "embeds": embeds
        }

        try:
            res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if res.status_code in [200, 204]:
                print(f"Successfully posted Discord message {chunk_index + 1}/{len(chunks)}!")
            else:
                print(f"Discord Webhook status {res.status_code}: {res.text}")
        except Exception as e:
            print(f"Error sending Discord Webhook: {e}")

        if chunk_index < len(chunks) - 1:
            time.sleep(2)  # avoid Discord webhook rate limits between messages

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
