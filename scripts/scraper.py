"""
Employment Law Tracker — Daily Scraper
=======================================
Pulls RSS feeds from major employment law firms and updates JSON data files.
Run daily via GitHub Actions.

Requirements:
    pip install feedparser requests beautifulsoup4

Usage:
    python scripts/scraper.py
"""

import json
import os
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path

try:
    import feedparser
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run: pip install feedparser requests beautifulsoup4")
    sys.exit(1)

# ── Configuration ──────────────────────────────────────────────────────────

DATA_DIR  = Path(__file__).parent.parent / "data"
TODAY_STR = date.today().isoformat()

COMPANY_SIZE = 500

# States we track (must match JSON file names)
TRACKED_STATES = [
    "arizona", "california", "colorado", "connecticut", "florida",
    "georgia", "illinois", "indiana", "kentucky", "massachusetts",
    "michigan", "minnesota", "new-jersey", "new-york", "north-carolina",
    "ohio", "pennsylvania", "tennessee", "texas", "utah",
    "virginia", "washington",
]

# State name aliases for matching article text
STATE_ALIASES = {
    "arizona": ["arizona", "AZ"],
    "california": ["california", "CA", "golden state"],
    "colorado": ["colorado", "CO"],
    "connecticut": ["connecticut", "CT"],
    "florida": ["florida", "FL"],
    "georgia": ["georgia", "GA"],
    "illinois": ["illinois", "IL", "chicago"],
    "indiana": ["indiana", "IN"],
    "kentucky": ["kentucky", "KY"],
    "massachusetts": ["massachusetts", "MA", "boston"],
    "michigan": ["michigan", "MI"],
    "minnesota": ["minnesota", "MN"],
    "new-jersey": ["new jersey", "NJ"],
    "new-york": ["new york", "NY", "NYC", "new york city"],
    "north-carolina": ["north carolina", "NC"],
    "ohio": ["ohio", "OH"],
    "pennsylvania": ["pennsylvania", "PA", "philadelphia", "pittsburgh"],
    "tennessee": ["tennessee", "TN"],
    "texas": ["texas", "TX", "dallas", "houston"],
    "utah": ["utah", "UT"],
    "virginia": ["virginia", "VA"],
    "washington": ["washington state", "WA", "seattle"],
}

# Keywords to SKIP (union-related content)
UNION_KEYWORDS = [
    "union", "collective bargaining", "nlra section 7", "strike",
    "labor organization", "bargaining unit", "unfair labor practice",
    "nlrb election", "union contract", "union organizing",
    "picketing", "lockout", "grievance procedure",
]

# Keywords that suggest federal law applicability
FEDERAL_KEYWORDS = [
    "federal", "DOL", "EEOC", "OSHA", "NLRB", "FLSA", "FMLA", "ADA",
    "title VII", "ADEA", "WARN", "ADA", "department of labor",
    "equal employment opportunity", "congress", "U.S.", "nationwide",
    "all employers", "all states",
]

# RSS Feeds from major employment law firms
# NOTE: These URLs should be verified periodically — law firms occasionally change their feed URLs.
RSS_FEEDS = [
    {
        "name": "Jackson Lewis",
        "url": "https://www.jacksonlewis.com/rss/insights",
        "fallback_url": "https://www.jacksonlewis.com/rss.xml",
    },
    {
        "name": "Littler",
        "url": "https://www.littler.com/rss.xml",
        "fallback_url": "https://www.littler.com/publication-search/rss",
    },
    {
        "name": "Ogletree Deakins",
        "url": "https://ogletree.com/feed/",
        "fallback_url": "https://ogletree.com/insights/feed/",
    },
    {
        "name": "Seyfarth Shaw",
        "url": "https://www.seyfarth.com/rss/insights.xml",
        "fallback_url": "https://www.seyfarth.com/rss.xml",
    },
    {
        "name": "Proskauer Rose",
        "url": "https://www.proskauer.com/rss.xml",
        "fallback_url": "https://www.proskauer.com/blogs/rss",
    },
]


# ── Helpers ────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"laws": [], "last_updated": TODAY_STR}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {path.name}")


def is_union_related(text: str) -> bool:
    """Return True if the article is primarily about union/labor organizing."""
    t = text.lower()
    hits = sum(1 for kw in UNION_KEYWORDS if kw.lower() in t)
    return hits >= 2  # Require at least 2 hits to avoid false positives


def detect_states(text: str) -> list[str]:
    """Return list of state slugs mentioned in the article."""
    t = text.lower()
    found = []
    for slug, aliases in STATE_ALIASES.items():
        for alias in aliases:
            if alias.lower() in t:
                found.append(slug)
                break
    return list(set(found))


def detect_federal(text: str) -> bool:
    """Return True if the article discusses federal-level law changes."""
    t = text.lower()
    return any(kw.lower() in t for kw in FEDERAL_KEYWORDS)


def detect_status(text: str) -> str:
    """Guess the status of a law change from the article text."""
    t = text.lower()
    if any(kw in t for kw in ["proposed", "bill introduced", "pending", "draft rule", "rulemaking"]):
        return "proposed"
    if any(kw in t for kw in ["repealed", "blocked", "vacated", "struck down", "enjoined", "overturned"]):
        return "repealed"
    if any(kw in t for kw in ["effective", "takes effect", "signed into law", "enacted", "in effect"]):
        if any(kw in t for kw in ["upcoming", "will take effect", "effective date", "january 1", "july 1"]):
            return "upcoming"
        return "recent"
    return "recent"


def detect_momentum(text: str) -> str:
    """Estimate legislative momentum for proposed laws."""
    t = text.lower()
    if any(kw in t for kw in ["signed", "passed both", "final vote", "expected to pass", "likely to pass"]):
        return "High"
    if any(kw in t for kw in ["committee", "advancing", "hearing scheduled", "second reading"]):
        return "Moderate"
    return "Low"


def extract_deadline(text: str) -> str | None:
    """Try to extract a compliance deadline date from article text."""
    # Look for patterns like "January 1, 2026", "July 1, 2025", "2026-01-01", etc.
    patterns = [
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+202[5-9]\b',
        r'\b202[5-9]-\d{2}-\d{2}\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                raw = match.group(0).replace(",", "")
                # Try to parse various formats
                for fmt in ["%B %d %Y", "%Y-%m-%d"]:
                    try:
                        dt = datetime.strptime(raw.strip(), fmt)
                        return dt.strftime("%Y-%m-%d")
                    except ValueError:
                        continue
            except Exception:
                pass
    return None


def detect_employee_threshold(text: str) -> int | None:
    """Detect if a law has a minimum employer size threshold."""
    patterns = [
        (r'(\d+)\s*or more employees', 1),
        (r'employers with (\d+)\+', 1),
        (r'(\d+)\s*\+\s*employees', 1),
        (r'at least (\d+) employees', 1),
    ]
    for pattern, group in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                n = int(match.group(group).replace(",", ""))
                if n > 1:
                    return n
            except ValueError:
                pass
    return None


def make_law_id(source_name: str, entry_id: str) -> str:
    """Generate a stable law ID from source and entry identifier."""
    source_prefix = source_name.lower().replace(" ", "")[:3]
    entry_hash = abs(hash(entry_id)) % 100000
    return f"{source_prefix}-{entry_hash}"


def fetch_feed(feed_config: dict) -> list[dict]:
    """Fetch and parse an RSS feed, returning a list of entry dicts."""
    articles = []

    for url in [feed_config["url"], feed_config.get("fallback_url")]:
        if not url:
            continue
        try:
            print(f"  Fetching {feed_config['name']} ({url})...")
            headers = {"User-Agent": "Mozilla/5.0 (compatible; EmploymentLawTrackerBot/1.0)"}
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"    HTTP {resp.status_code} — trying fallback...")
                continue

            feed = feedparser.parse(resp.content)
            if not feed.entries:
                print(f"    No entries found — trying fallback...")
                continue

            for entry in feed.entries[:20]:  # Process latest 20 entries
                title   = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                link    = entry.get("link", "")
                pub_date = entry.get("published", TODAY_STR)

                # Combine for analysis
                full_text = f"{title} {summary}"

                # Skip union-related content
                if is_union_related(full_text):
                    continue

                articles.append({
                    "source": feed_config["name"],
                    "title": title,
                    "summary": BeautifulSoup(summary, "html.parser").get_text(separator=" ")[:600],
                    "link": link,
                    "full_text": full_text,
                    "pub_date": pub_date,
                })

            print(f"    Found {len(articles)} relevant articles.")
            return articles

        except Exception as e:
            print(f"    Error fetching {url}: {e}")
            continue

    print(f"  Could not fetch {feed_config['name']} — skipping.")
    return []


def article_to_law(article: dict, jurisdiction: str = "Federal") -> dict:
    """Convert a raw article dict into a law entry dict."""
    text = article["full_text"]
    status = detect_status(text)
    threshold = detect_employee_threshold(text)
    deadline = extract_deadline(text)

    return {
        "id": make_law_id(article["source"], article["link"]),
        "title": article["title"],
        "status": status,
        "effective_date": deadline,
        "deadline": deadline,
        "summary": (
            f"{article['summary'][:400].strip()}… "
            f"[This entry was auto-pulled from {article['source']}. "
            f"Review the source article for full details and verify with your employment counsel before taking compliance action.]"
        ),
        "applies_to_company": (threshold is None or threshold <= COMPANY_SIZE),
        "min_employee_threshold": threshold,
        "employee_threshold_note": (
            f"Applies to employers with {threshold}+ employees" if threshold else None
        ),
        "compliance_actions": [
            "⚠️ This entry was auto-detected from an RSS feed. Review the source article.",
            "Consult your employment counsel before taking compliance action.",
            f"Read the full article: {article['link']}",
        ],
        "source": article["source"],
        "source_url": article["link"],
        "tags": [],
        "momentum_level": detect_momentum(text) if status == "proposed" else None,
        "repeal_notes": None,
        "last_updated": TODAY_STR,
        "_auto_generated": True,
        "_needs_review": True,
    }


def existing_ids(laws: list[dict]) -> set[str]:
    return {l["id"] for l in laws}


# ── Main Logic ─────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*60}")
    print(f"Employment Law Tracker — Daily Scrape ({TODAY_STR})")
    print(f"{'='*60}\n")

    # 1. Collect all articles from all RSS feeds
    all_articles = []
    for feed in RSS_FEEDS:
        articles = fetch_feed(feed)
        all_articles.extend(articles)
        time.sleep(1)  # Be polite

    if not all_articles:
        print("\n⚠️  No articles fetched. Check RSS feed URLs.")
        return

    print(f"\nTotal articles fetched: {len(all_articles)}")

    # 2. Load existing data
    federal_path = DATA_DIR / "federal.json"
    federal_data = load_json(federal_path)

    state_data = {}
    for slug in TRACKED_STATES:
        path = DATA_DIR / "states" / f"{slug}.json"
        state_data[slug] = load_json(path)

    # 3. Classify and add new articles
    new_federal = 0
    new_state   = {s: 0 for s in TRACKED_STATES}

    fed_existing_ids  = existing_ids(federal_data["laws"])
    state_existing    = {s: existing_ids(state_data[s]["laws"]) for s in TRACKED_STATES}

    for article in all_articles:
        full_text    = article["full_text"]
        states_found = detect_states(full_text)
        is_federal   = detect_federal(full_text)

        # Add to relevant state files
        for slug in states_found:
            if slug in TRACKED_STATES:
                law = article_to_law(article, jurisdiction=slug)
                if law["id"] not in state_existing[slug]:
                    state_data[slug]["laws"].append(law)
                    state_existing[slug].add(law["id"])
                    new_state[slug] += 1

        # Add to federal file if federal-relevant and no specific state detected
        if is_federal and not states_found:
            law = article_to_law(article, jurisdiction="Federal")
            if law["id"] not in fed_existing_ids:
                federal_data["laws"].append(law)
                fed_existing_ids.add(law["id"])
                new_federal += 1

    # 4. Update timestamps and save
    if new_federal > 0:
        federal_data["last_updated"] = TODAY_STR
        save_json(federal_path, federal_data)
        print(f"  Federal: +{new_federal} new entries")

    for slug in TRACKED_STATES:
        if new_state[slug] > 0:
            state_data[slug]["last_updated"] = TODAY_STR
            path = DATA_DIR / "states" / f"{slug}.json"
            save_json(path, state_data[slug])
            print(f"  {slug}: +{new_state[slug]} new entries")

    total_new = new_federal + sum(new_state.values())
    print(f"\n✅ Done. {total_new} new entries added across all jurisdictions.")
    print("⚠️  Auto-generated entries are marked '_needs_review: true' — review before relying on them.\n")


if __name__ == "__main__":
    run()
