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

# Post a short "I ran today" note to Discord even when there are no new opportunities,
# so silence is never ambiguous. Set POST_HEARTBEAT=1 in the workflow env to enable.
POST_HEARTBEAT = os.getenv("POST_HEARTBEAT", "").strip() not in ("", "0", "false", "False")

# Generic nav/share links that sometimes match our keyword filters but aren't real opportunities
NON_OPPORTUNITY_TITLES = {
    "twitter", "facebook", "instagram", "linkedin", "share", "email", "print",
    "tweet", "pinterest", "youtube", "x", "learn more", "public art", "artist calls",
    "see all articles", "all news", "all events", "all projects", "back to arts",
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

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PublicArtTracker/1.0; +https://github.com/vpaitoon/public-art-tracker)"}

# raleighnc.gov started returning a Cloudflare "Just a moment..." JS challenge (HTTP 403)
# to plain requests.get() as of ~2026-08-27, site-wide (listing pages and individual
# opportunity pages alike). Route those fetches through a real headless browser instead.
PLAYWRIGHT_DOMAINS = ["raleighnc.gov"]


def fetch_rendered_html(url, timeout_ms=20000, max_challenge_wait_s=15):
    """Load a page with headless Chromium so a Cloudflare JS challenge has a chance to
    clear before we read the HTML. Spins up a fresh browser per call for simplicity;
    fine at this scanner's low daily volume."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            waited = 0
            while "just a moment" in page.title().strip().lower() and waited < max_challenge_wait_s:
                page.wait_for_timeout(1000)
                waited += 1
            html = page.content()
        finally:
            browser.close()
    return html


def fetch_html(url, timeout=15):
    """Fetch a URL's HTML, transparently falling back to a headless browser for domains
    known to block plain HTTP clients (see PLAYWRIGHT_DOMAINS). Returns None on failure."""
    if any(d in url.lower() for d in PLAYWRIGHT_DOMAINS):
        try:
            return fetch_rendered_html(url, timeout_ms=timeout * 1000)
        except Exception as e:
            print(f"Headless-browser fetch failed for {url}: {e}")
            return None
    try:
        res = requests.get(url, headers=HEADERS, timeout=timeout)
        if res.status_code == 200:
            return res.text
        print(f"Non-200 status {res.status_code} for {url}")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None


def fetch_opportunity_details(url):
    """Fetch an individual opportunity's page and pull out a summary, budget, and due date."""
    details = {"summary": "No summary available.", "budget": "Not specified", "due_date": "Not specified"}
    try:
        html = fetch_html(url)
        if not html:
            return details
        soup = BeautifulSoup(html, "html.parser")

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


def _clean_title(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def fetch_raleigh_arts():
    """
    Raleigh lists real calls in content sections that each have a heading (h2) and a
    "Learn more about the <Call>" link, plus a "Support Pages" list of opportunity links.

    The old version only accepted links whose URL contained artist-call / public-art /
    seek-raleigh, which SKIPPED valid calls like "Fall Arts Fair"
    (/arts/services/arts-centers/fall-arts-fair). We now:
      1. Walk each opportunity <h2> section and grab its heading + first raleighnc.gov link.
      2. Fall back to the "Support Pages" list and the old keyword filter.
      3. De-duplicate by URL.
    """
    url = "https://raleighnc.gov/arts/services/artist-calls"
    opportunities = []
    by_url = {}

    # Path fragments that indicate an actual opportunity/toolkit page (broadened).
    OPP_URL_HINTS = [
        "artist-call", "public-art", "seek-raleigh", "propose-public-art",
        "arts-centers/", "block", "medal-arts", "calls",
    ]
    # Section headings we never treat as opportunities.
    SKIP_HEADINGS = {"jump to:", "share", "contact", "subscribe", "support pages",
                     "related news", "related events", "related projects"}

    def _add(title, href):
        title = _clean_title(title)
        if not href:
            return
        if not (href.startswith("/") or "raleighnc.gov" in href.lower()):
            return
        full_url = href if href.startswith("http") else f"https://raleighnc.gov{href}"
        full_url = full_url.split("#")[0].rstrip("/")
        if full_url.rstrip("/") == url.rstrip("/"):
            return
        low = full_url.lower()
        if not any(h in low for h in OPP_URL_HINTS):
            return
        if len(title) <= 5 or title.lower() in NON_OPPORTUNITY_TITLES:
            return
        if full_url not in by_url:
            by_url[full_url] = {
                "id": full_url,
                "title": title,
                "organization": "City of Raleigh Arts",
                "location": "Raleigh, NC",
                "state": "NC",
                "url": full_url,
                "budget": "Varies by project",
                "category": "Municipal Public Art",
            }

    try:
        html = fetch_html(url)
        if html:
            soup = BeautifulSoup(html, "html.parser")

            # 1) Section-based: each opportunity h2 followed by a "Learn more" link.
            for h2 in soup.find_all(["h2", "h3"]):
                heading = _clean_title(h2.get_text())
                if not heading or heading.lower() in SKIP_HEADINGS:
                    continue
                # Look at the siblings until the next heading for the first in-site link.
                link_href = None
                for sib in h2.find_all_next():
                    if sib.name in ("h2", "h3"):
                        break
                    if sib.name == "a" and sib.get("href"):
                        href = sib["href"]
                        if href.startswith("/") or "raleighnc.gov" in href.lower():
                            link_href = href
                            break
                if link_href:
                    _add(heading, link_href)

            # 2) Fallback: every plausible opportunity link on the page (Support Pages, etc.)
            for a in soup.find_all("a", href=True):
                _add(a.get_text(strip=True), a["href"])

        opportunities = list(by_url.values())
    except Exception as e:
        print(f"Error fetching Raleigh Arts: {e}")
    return opportunities

def fetch_durham_arts():
    """
    Durham's page is a JavaScript-rendered CivicPlus site, so plain requests() may
    receive a shell without the listings (watch for the 0-result warning in main()).

    The old version required each link's TEXT to contain "durham" AND the URL to
    contain rfq/public-art/call-for -- far too strict; it dropped real calls like the
    "Pre-Qualified Artist Registry" and the current mural call. We now:
      1. Walk content headings that look like a call/registry and grab the nearest
         application link (Submittable, registry, a numeric CivicPlus project page).
      2. Fall back to any application/opportunity link on the page.
      3. De-duplicate by URL.
    """
    url = "https://www.durhamnc.gov/2984/Durham-Calls-for-Artists"
    opportunities = []
    by_url = {}

    NAV_STOP = {
        "home", "departments", "contact us", "questions?", "resources & faqs",
        "public art map", "public art collection", "public art committee",
        "annual reports", "durham cultural roadmap", "durham poet laureate",
        "public art collection", "current public art projects", "guidelines",
        "sign up for email alerts", "project overview", "submission requirements",
    }
    # Heading text that signals an actual opportunity.
    HEAD_HINTS = ["call for artist", "calls for artist", "registry", "mural",
                  "public art project", "artist opportunit", "request for qual", "rfq"]
    # URL fragments that signal an application/opportunity link.
    LINK_HINTS = ["submittable", "registry", "rfq", "call-for", "calls-for",
                  "public-art", "mural", "apply", "opportunit"]

    def _add(title, href, category="Municipal Public Art"):
        title = _clean_title(title)
        if not href:
            return
        full_url = href if href.startswith("http") else f"https://www.durhamnc.gov{href}"
        full_url = full_url.split("#")[0].rstrip("/")
        if full_url.rstrip("/") == url.rstrip("/"):
            return
        tl = title.lower()
        if len(title) <= 8 or tl in NAV_STOP or tl in NON_OPPORTUNITY_TITLES:
            return
        if full_url not in by_url:
            by_url[full_url] = {
                "id": full_url,
                "title": title,
                "organization": "City of Durham Cultural & Public Art Program",
                "location": "Durham, NC",
                "state": "NC",
                "url": full_url,
                "budget": "Varies",
                "category": category,
            }

    try:
        html = fetch_html(url)
        if html:
            soup = BeautifulSoup(html, "html.parser")

            # 1) Heading-driven: opportunity heading + nearest application link.
            for h in soup.find_all(["h1", "h2", "h3"]):
                heading = _clean_title(h.get_text())
                hl = heading.lower()
                if len(heading) <= 8 or hl in NAV_STOP:
                    continue
                if not any(k in hl for k in HEAD_HINTS):
                    continue
                link_href = None
                for sib in h.find_all_next():
                    if sib.name in ("h1", "h2", "h3"):
                        break
                    if sib.name == "a" and sib.get("href"):
                        if any(k in sib["href"].lower() for k in LINK_HINTS):
                            link_href = sib["href"]
                            break
                _add(heading, link_href or f"{url}#{re.sub(r'[^a-z0-9]+', '-', hl)}")

            # 2) Link-driven fallback: any application/opportunity link.
            for a in soup.find_all("a", href=True):
                title = _clean_title(a.get_text())
                href = a["href"]
                if not (href.startswith("/") or "durhamnc.gov" in href.lower()
                        or "submittable" in href.lower()):
                    continue
                if any(k in href.lower() for k in LINK_HINTS) or any(
                        k in title.lower() for k in
                        ["call for artist", "registry", "mural", "public art", "rfq"]):
                    _add(title, href)

        opportunities = list(by_url.values())
    except Exception as e:
        print(f"Error fetching Durham Arts: {e}")
    return opportunities

def fetch_triangle_artworks():
    """
    Triangle ArtWorks is a Wix site. Plain requests() may receive a JavaScript shell
    without the listings, in which case this returns 0 items -- see the 0-result
    warning in main(). If that happens consistently, this source needs a rendered
    fetch (e.g. a headless browser / an external render service) or the site's data API.
    """
    url = "https://www.triangleartworks.org/calls-for-artists"
    opportunities = []
    seen_here = set()
    KEYWORDS = ["public art", "mural", "rfq", "commission", "call for", "calls for",
                "request for qualifications", "artist call", "exhibition", "registry"]
    try:
        html = fetch_html(url)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                title = _clean_title(a.get_text())
                href = a["href"]
                if title.lower() in NON_OPPORTUNITY_TITLES:
                    continue
                if len(title) > 10 and any(kw in title.lower() for kw in KEYWORDS):
                    full_url = href if href.startswith("http") else f"https://www.triangleartworks.org{href}"
                    if full_url.rstrip("/") == url.rstrip("/"):
                        continue
                    key = full_url + "|" + title.lower()
                    if key in seen_here:
                        continue
                    seen_here.add(key)
                    opportunities.append({
                        "id": full_url if full_url.rstrip("/") != url.rstrip("/") else f"{url}#{title.lower()}",
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

# How many pages of the NC Arts Council listing to read (sorted soonest-deadline first).
NC_ARTS_PAGES = 2
# Categories / keywords that make an NC Arts Council listing relevant to a public-art
# commission tracker. Filters out dance intensives, writing workshops, generic
# online competitions, etc. that the aggregator also carries.
NC_RELEVANT_TERMS = [
    "public art", "mural", "sculpture", "commission", "rfq",
    "request for qualifications", "call for artist", "call to artist",
    "crosswalk", "installation", "artist residency", "artist call",
]

def _parse_nc_arts_table(soup):
    items = []
    # Find the opportunities table (header includes "Opportunity"/"Deadline"),
    # not the "College or university" table.
    opp_table = None
    for tb in soup.find_all("table"):
        headers = " ".join(th.get_text(" ", strip=True).lower() for th in tb.find_all("th"))
        if "opportunity" in headers or "deadline" in headers:
            opp_table = tb
            break
    if opp_table is None:
        return items

    for tr in opp_table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        category = _clean_title(tds[0].get_text(" "))
        opp_cell = tds[1]
        a = opp_cell.find("a", href=True)
        if not a:
            continue
        title = _clean_title(a.get_text())
        href = a["href"]
        if len(title) <= 5 or title.lower() in NON_OPPORTUNITY_TITLES:
            continue
        deadline = _clean_title(tds[2].get_text(" ")) if len(tds) >= 3 else "Not specified"

        haystack = f"{category} {opp_cell.get_text(' ', strip=True)}".lower()
        if "public art" not in category.lower() and not any(t in haystack for t in NC_RELEVANT_TERMS):
            continue

        full_url = href if href.startswith("http") else f"https://www.ncarts.org{href}"
        org = title.split("|")[0].strip() if "|" in title else "NC Arts Council listing"
        items.append({
            "id": full_url,
            "title": title,
            "organization": org,
            "location": "North Carolina / Regional",
            "state": "NC",
            "url": full_url,
            "budget": "See listing",
            "category": category or "Statewide Call",
            "_due_date": deadline,
        })
    return items

def fetch_nc_arts_council():
    """
    NC Arts Council aggregates public-art calls from across the state (including Durham
    and Raleigh) in a server-rendered, sortable table. The old version only matched a
    link whose TEXT contained public-art/commission/etc., which dropped almost every
    listing because titles are org-named (e.g. "The Scrap Exchange | Crosswalk Project").
    We now parse the opportunities TABLE row-by-row (category + link + deadline) and keep
    rows relevant to public art, across the first NC_ARTS_PAGES pages (soonest deadlines).
    """
    base = "https://www.ncarts.org/grants-resources/resources/artists/artist-opportunities"
    opportunities = []
    by_url = {}
    try:
        for page in range(NC_ARTS_PAGES):
            page_url = base if page == 0 else f"{base}?page={page}"
            html = fetch_html(page_url)
            if not html:
                break
            soup = BeautifulSoup(html, "html.parser")
            rows = _parse_nc_arts_table(soup)
            if not rows and page > 0:
                break
            for item in rows:
                if item["id"] not in by_url:
                    by_url[item["id"]] = item
        opportunities = list(by_url.values())
    except Exception as e:
        print(f"Error fetching NC Arts Council: {e}")
    return opportunities

DISCORD_EMBEDS_PER_MESSAGE = 10

def build_embed(item):
    details = fetch_opportunity_details(item["url"])
    time.sleep(1)  # be polite to the source sites between detail-page fetches
    # Prefer a deadline the source listing already gave us (e.g. NC Arts Council table).
    if details["due_date"] == "Not specified" and item.get("_due_date"):
        details["due_date"] = item["_due_date"]
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

def _post_payload(payload, label):
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if res.status_code in [200, 204]:
            print(f"Successfully posted Discord message: {label}")
            return True
        print(f"Discord Webhook status {res.status_code} for {label}: {res.text}")
    except Exception as e:
        print(f"Error sending Discord Webhook ({label}): {e}")
    return False

def send_heartbeat(total_fetched, per_source):
    if not DISCORD_WEBHOOK_URL:
        return
    breakdown = ", ".join(f"{name}: {n}" for name, n in per_source)
    payload = {
        "username": "Public Art Commission Tracker",
        "content": (f"✅ Daily scan ran — no *new* opportunities today. "
                    f"Checked {total_fetched} listings ({breakdown})."),
    }
    _post_payload(payload, "heartbeat")

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

        _post_payload(payload, f"{chunk_index + 1}/{len(chunks)}")

        if chunk_index < len(chunks) - 1:
            time.sleep(2)  # avoid Discord webhook rate limits between messages

def main():
    print(f"[{datetime.now().isoformat()}] Starting Public Art Commission Scan...")
    seen_ids = load_seen()
    all_opportunities = []
    per_source = []

    for name, fn in [
        ("City of Raleigh Arts", fetch_raleigh_arts),
        ("Durham Calls for Artists", fetch_durham_arts),
        ("Triangle ArtWorks", fetch_triangle_artworks),
        ("NC Arts Council", fetch_nc_arts_council),
    ]:
        items = fn()
        per_source.append((name, len(items)))
        print(f"  {name}: {len(items)} listings")
        if len(items) == 0:
            print(f"  ⚠️  WARNING: {name} returned 0 listings — the page markup may have "
                  f"changed or requires JavaScript rendering. New calls here will be missed.")
        all_opportunities.extend(items)

    new_opportunities = [item for item in all_opportunities if item["id"] not in seen_ids]

    print(f"Total fetched: {len(all_opportunities)} | New items: {len(new_opportunities)}")

    if new_opportunities:
        send_discord_webhook(new_opportunities)
        for item in new_opportunities:
            seen_ids.add(item["id"])
        save_seen(seen_ids)
    else:
        print("No new opportunities found today.")
        if POST_HEARTBEAT:
            send_heartbeat(len(all_opportunities), per_source)

if __name__ == "__main__":
    main()
