"""Employment Law Tracker — Daily Scraper (v2)
==========================================
Pulls RSS feeds from major employment law firms and updates JSON data files.

CONTENT CRITERIA — Only includes articles that:
  1. Are actual US laws, regulations, or binding compliance requirements
  2. Are NOT law firm PR, awards, staff hires, or promotional content
  3. Are NOT about non-US jurisdictions (UK, EU, Australia, etc.)
  4. Are NOT primarily about union organizing (site serves non-union employers)
  5. Have enough legal substance (compliance deadlines, employer obligations, etc.)
  6. Are assigned only to states they actually name in the title or opening sentence

Run daily via GitHub Actions.
Requirements: pip install feedparser requests beautifulsoup4
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

DATA_DIR = Path(__file__).parent.parent / "data"
TODAY_STR = date.today().isoformat()
COMPANY_SIZE = 500

TRACKED_STATES = [
    "arizona", "california", "colorado", "connecticut", "florida", "georgia",
    "illinois", "indiana", "kentucky", "massachusetts", "michigan", "minnesota",
    "new-jersey", "new-york", "north-carolina", "ohio", "pennsylvania",
    "tennessee", "texas", "utah", "virginia", "washington",
]

STATE_ALIASES = {
    "arizona": ["arizona"], "california": ["california"], "colorado": ["colorado"],
    "connecticut": ["connecticut"], "florida": ["florida"], "georgia": ["georgia"],
    "illinois": ["illinois", "chicago"], "indiana": ["indiana"],
    "kentucky": ["kentucky"], "massachusetts": ["massachusetts", "boston"],
    "michigan": ["michigan"], "minnesota": ["minnesota"],
    "new-jersey": ["new jersey"], "new-york": ["new york", "nyc", "new york city"],
    "north-carolina": ["north carolina"], "ohio": ["ohio"],
    "pennsylvania": ["pennsylvania", "philadelphia", "pittsburgh"],
    "tennessee": ["tennessee"], "texas": ["texas", "dallas", "houston"],
    "utah": ["utah"], "virginia": ["virginia"],
    "washington": ["washington state", "seattle"],
}

FIRM_PR_TITLE_PATTERNS = [
    r'\b(discusses|comments on|weighs in on|examines|talks about|addresses)\b',
    r'\b(welcomes|honors|recognizes|celebrates|advances|earns|named|ranks|joins)\b.{0,60}\b(firm|attorney|lawyer|counsel|principal|partner|associate)\b',
    r'\b(attorney|lawyer|counsel|principal|partner|associate)\b.{0,60}\b(award|honor|recogni|named|ranked|stand.?out|super lawyer|best law)\b',
    r'chambers (global|usa|guide|rank)', r'stand-?out lawyers?', r'best law firms?',
    r'super lawyers?', r'^dear (littler|jackson lewis|ogletree|seyfarth|proskauer)',
    r'^littler lounge', r'^policy week in review', r'^celebrating\b',
    r'\bblack history month\b',
    r'\b(podcast|webinar|seminar|conference|event|master class|preview of)\b',
    r'\b(joins|joining|joined) (the firm|as principal|as partner|as associate|as counsel)\b',
    r'\bnew hire\b', r'expands?.{0,30}(practice|office|team)',
    r'week in review', r'month in review',
]
FIRM_PR_URL_PATTERNS = [r'/firm/news-and-press/', r'/news-and-press/', r'/press-release']

INTERNATIONAL_TITLE_PREFIXES = [
    "uk:", "u.k.:", "united kingdom:", "england:", "wales:", "scotland:",
    "australia:", "canada:", "denmark:", "eu:", "europe:", "european:",
    "france:", "germany:", "netherlands:", "ireland:", "india:", "china:",
    "japan:", "south korea:", "brazil:", "mexico:", "singapore:", "spain:",
    "italy:", "sweden:", "norway:", "switzerland:", "new zealand:", "hong kong:",
    "belgium:", "austria:", "portugal:", "poland:", "czech:", "romania:",
    "turkey:", "israel:", "south africa:", "puerto rico:",
]
INTERNATIONAL_TITLE_PHRASES = [
    r'\benglish law\b', r'\bunder english\b', r'\buk employment\b', r'\btupe\b',
    r'\bfair work commission\b', r'\bemployment appeal tribunal\b',
    r'\bemployment tribunal\b', r'\beu pay transparency directive\b',
    r'\beu directive\b', r'\beuropean court\b',
    r'\bsouth korea.{0,20}(law|act|rule|regulation|employer)\b',
    r'\bexpanding.{0,30}into (brazil|china|india|europe|canada|uk|mexico)\b',
]

UNION_FOCUS_PHRASES = [
    r'\bunion organizing\b', r'\bcollective bargaining agreement\b',
    r'\bnlrb election\b', r'\bbargaining unit\b', r'\bunfair labor practice\b',
    r'\bpicketing\b', r'\bunion contract\b',
    r'\bstrike\b.{0,30}\b(worker|employee|labor)\b',
    r'\blabor organization\b', r'\bmerger doctrine\b',
    r'\bnlrb member\b', r'\bnlrb.{0,40}\bdoctor?ine\b',
]

LAW_SUBSTANCE_KEYWORDS = [
    "enacted", "effective", "takes effect", "effective date", "in effect",
    "in force", "now requires", "compliance", "comply", "required",
    "requires employers", "employers must", "employer must", "mandate", "mandatory",
    "law", "regulation", "rule", "statute", "bill", "ordinance", "act",
    "obligation", "violation", "penalty", "penalties", "fine", "enforcement",
    "deadline", "signed into law", "passed", "promulgated",
    "final rule", "proposed rule", "rulemaking", "public comment",
    "department of labor", "dol", "eeoc", "osha",
    "minimum wage", "overtime", "paid leave", "sick leave",
    "discrimination", "harassment", "pay transparency", "salary range",
    "worker classification", "independent contractor", "misclassification",
    "background check", "non-compete", "noncompete",
    "meal break", "rest period", "predictive scheduling", "fair workweek",
    "pay equity", "equal pay", "family leave", "parental leave", "fmla",
    "ada accommodation", "reasonable accommodation", "i-9", "e-verify",
    "posting requirement", "notice requirement", "retaliation", "whistleblower",
    "drug testing", "ban the box",
]

RSS_FEEDS = [
    {"name": "Jackson Lewis", "url": "https://www.jacksonlewis.com/rss/insights"},
    {"name": "Littler", "url": "https://www.littler.com/rss.xml",
     "fallback_url": "https://www.littler.com/publication-search/rss"},
    {"name": "Ogletree Deakins", "url": "https://ogletree.com/feed/",
     "fallback_url": "https://ogletree.com/insights/feed/"},
    {"name": "Seyfarth Shaw", "url": "https://www.seyfarth.com/rss/insights.xml",
     "fallback_url": "https://www.seyfarth.com/rss.xml"},
]


def is_firm_pr(title, url=""):
    t = title.lower()
    for p in FIRM_PR_TITLE_PATTERNS:
        if re.search(p, t, re.IGNORECASE): return True
    for p in FIRM_PR_URL_PATTERNS:
        if re.search(p, url, re.IGNORECASE): return True
    return False

def is_international(title, summary=""):
    t = title.lower().strip()
    for prefix in INTERNATIONAL_TITLE_PREFIXES:
        if t.startswith(prefix): return True
    for phrase in INTERNATIONAL_TITLE_PHRASES:
        if re.search(phrase, t, re.IGNORECASE): return True
    return False

def is_union_focused(title, summary):
    combined = (title + " " + summary[:500]).lower()
    for phrase in UNION_FOCUS_PHRASES:
        if re.search(phrase, combined, re.IGNORECASE): return True
    return False

def has_law_substance(title, summary):
    combined = (title + " " + summary[:600]).lower()
    return sum(1 for kw in LAW_SUBSTANCE_KEYWORDS if kw.lower() in combined) >= 2

def should_include(title, summary, url=""):
    if is_firm_pr(title, url): return False, "firm_pr"
    if is_international(title, summary): return False, "international"
    if is_union_focused(title, summary): return False, "union_focused"
    if not has_law_substance(title, summary): return False, "no_substance"
    return True, "ok"

def detect_states_from_title(title):
    t = title.lower()
    found = []
    for slug, aliases in STATE_ALIASES.items():
        for alias in aliases:
            if re.search(r'\b' + re.escape(alias.lower()) + r'\b', t):
                found.append(slug); break
    return list(set(found))

def detect_states_from_opening(summary):
    text = summary[:200].lower()
    found = []
    for slug, aliases in STATE_ALIASES.items():
        for alias in aliases:
            if re.search(r'\b' + re.escape(alias.lower()) + r'\b', text):
                found.append(slug); break
    return list(set(found))

def detect_states(title, summary):
    title_states = detect_states_from_title(title)
    if title_states: return title_states
    opening_states = detect_states_from_opening(summary)
    if len(opening_states) == 1: return opening_states
    return []

def is_federal_topic(title, summary):
    signals = ["federal", "u.s. department", "department of labor", "dol ",
               "eeoc", "osha", "flsa", "fmla", " ada ", "nlrb", "nationwide",
               "all employers", "congress", "executive order", "supreme court",
               "federal court", "federal register"]
    combined = (title + " " + summary[:300]).lower()
    return any(s in combined for s in signals)

def load_json(path):
    if path.exists():
        with open(path) as f: return json.load(f)
    return {"laws": [], "last_updated": TODAY_STR}

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)
    print(f"  Saved: {path.name}")

def clean_html(text):
    return BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()

def detect_status(text):
    t = text.lower()
    if any(kw in t for kw in ["proposed", "bill introduced", "pending", "draft rule",
                               "rulemaking", "public comment"]): return "proposed"
    if any(kw in t for kw in ["repealed", "blocked", "vacated", "struck down",
                               "enjoined", "overturned", "withdrawn"]): return "repealed"
    if any(kw in t for kw in ["upcoming", "will take effect", "takes effect",
                               "effective date", "effective january"]): return "upcoming"
    return "recent"

def detect_momentum(text):
    t = text.lower()
    if any(kw in t for kw in ["signed", "passed both", "final vote"]): return "High"
    if any(kw in t for kw in ["committee", "advancing", "hearing scheduled"]): return "Moderate"
    return "Low"

def extract_deadline(text):
    for pattern in [r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+202[5-9]\b', r'\b202[5-9]-\d{2}-\d{2}\b']:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                raw = m.group(0).replace(",", "").strip()
                for fmt in ["%B %d %Y", "%Y-%m-%d"]:
                    try: return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                    except ValueError: continue
            except: pass
    return None

def detect_employee_threshold(text):
    for pattern in [r'(\d+)\s*or more employees', r'employers with (\d+)\+', r'at least (\d+) employees']:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                n = int(m.group(1).replace(",", ""))
                if 1 < n <= 2000: return n
            except: pass
    return None

def make_law_id(source_name, link):
    return f"{source_name.lower().replace(' ', '')[:3]}-{abs(hash(link)) % 100000}"

def existing_ids(laws):
    return {l["id"] for l in laws}


def existing_titles(laws):
    """Normalized title set for dedup by title (catches same article at different URLs)."""
    return {l["title"].strip().lower() for l in laws}

def fetch_feed(feed_config):
    articles = []
    for url in [u for u in [feed_config.get("url"), feed_config.get("fallback_url")] if u]:
        try:
            print(f"  Fetching {feed_config['name']} ({url})...")
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EmploymentLawTrackerBot/1.0)"}, timeout=15)
            if resp.status_code != 200: continue
            feed = feedparser.parse(resp.content)
            if not feed.entries: continue
            for entry in feed.entries[:30]:
                title = entry.get("title", "").strip()
                if not title: continue
                summary = clean_html(entry.get("summary", entry.get("description", "")))[:800]
                articles.append({"source": feed_config["name"], "title": title, "summary": summary, "link": entry.get("link", "")})
            print(f"  Got {len(articles)} entries")
            return articles
        except Exception as e: print(f"  Error: {e}")
    print(f"  Could not fetch {feed_config['name']}")
    return []

def article_to_law(article, jurisdiction="Federal"):
    text = f"{article['title']} {article['summary']}"
    status = detect_status(text)
    threshold = detect_employee_threshold(text)
    deadline = extract_deadline(text)
    return {
        "id": make_law_id(article["source"], article["link"]),
        "title": article["title"], "status": status,
        "effective_date": deadline, "deadline": deadline,
        "summary": (f"{article['summary'][:400].strip()}... "
                    f"[Auto-detected from {article['source']} RSS. Verify with employment counsel.]"),
        "applies_to_company": (threshold is None or threshold <= COMPANY_SIZE),
        "min_employee_threshold": threshold,
        "employee_threshold_note": (f"Applies to employers with {threshold}+ employees" if threshold else None),
        "compliance_actions": [
            "Auto-detected from RSS feed. Review source article for accuracy.",
            "Consult your employment counsel before taking compliance action.",
            f"Read the full article: {article['link']}",
        ],
        "source": article["source"], "source_url": article["link"], "tags": [],
        "momentum_level": detect_momentum(text) if status == "proposed" else None,
        "repeal_notes": None, "last_updated": TODAY_STR,
        "_auto_generated": True, "_needs_review": True,
    }

def clean_existing_data():
    print("\n-- Cleaning existing auto-generated entries --")
    total_removed = 0
    for slug in TRACKED_STATES:
        path = DATA_DIR / "states" / f"{slug}.json"
        if not path.exists(): continue
        data = load_json(path)
        before = len(data["laws"])
        valid = []
        for law in data["laws"]:
            if not law.get("_auto_generated"):
                valid.append(law); continue
            include, _ = should_include(law.get("title",""), law.get("summary",""), law.get("source_url",""))
            if not include: continue
            state_matches = detect_states(law.get("title",""), law.get("summary",""))
            if state_matches and slug in state_matches:
                valid.append(law)
        removed = before - len(valid)
        if removed > 0:
            data["laws"] = valid
            data["last_updated"] = TODAY_STR
            save_json(path, data)
            total_removed += removed
            print(f"  {slug}.json: removed {removed} ({len(valid)} remain)")
    print(f"  Total removed: {total_removed}\n")

def run():
    print(f"\n{'='*60}")
    print(f"Employment Law Tracker -- Daily Scrape ({TODAY_STR})")
    print(f"{'='*60}")
    clean_existing_data()
    all_articles = []
    for feed_config in RSS_FEEDS:
        all_articles.extend(fetch_feed(feed_config))
        time.sleep(1)
    if not all_articles:
        print("No articles fetched."); return
    print(f"\nTotal fetched: {len(all_articles)}")
    federal_path = DATA_DIR / "federal.json"
    federal_data = load_json(federal_path)
    state_data = {s: load_json(DATA_DIR / "states" / f"{s}.json") for s in TRACKED_STATES}
    fed_ids = existing_ids(federal_data["laws"])
    fed_titles = existing_titles(federal_data["laws"])
    state_ids = {s: existing_ids(state_data[s]["laws"]) for s in TRACKED_STATES}
    state_titles = {s: existing_titles(state_data[s]["laws"]) for s in TRACKED_STATES}
    stats = {"firm_pr": 0, "international": 0, "union_focused": 0, "no_substance": 0, "no_jurisdiction": 0}
    new_federal = 0
    new_state = {s: 0 for s in TRACKED_STATES}
    for article in all_articles:
        title, summary, url = article["title"], article["summary"], article["link"]
        include, reason = should_include(title, summary, url)
        if not include:
            stats[reason] = stats.get(reason, 0) + 1
            print(f"  SKIP [{reason}] {title[:75]}"); continue
        state_matches = detect_states(title, summary)
        if state_matches:
            for slug in state_matches:
                if slug not in TRACKED_STATES: continue
                law = article_to_law(article, jurisdiction=slug)
                title_key = title.strip().lower()
                if law["id"] not in state_ids[slug] and title_key not in state_titles[slug]:
                    state_data[slug]["laws"].append(law)
                    state_ids[slug].add(law["id"])
                    state_titles[slug].add(title_key)
                    new_state[slug] += 1
                    print(f"  ADD [{slug}] {title[:60]}")
        elif is_federal_topic(title, summary):
            law = article_to_law(article, jurisdiction="Federal")
            title_key = title.strip().lower()
            if law["id"] not in fed_ids and title_key not in fed_titles:
                federal_data["laws"].append(law)
                fed_ids.add(law["id"])
                fed_titles.add(title_key)
                new_federal += 1
                print(f"  ADD [federal] {title[:60]}")
        else:
            stats["no_jurisdiction"] = stats.get("no_jurisdiction", 0) + 1
    if new_federal > 0:
        federal_data["last_updated"] = TODAY_STR
        save_json(federal_path, federal_data)
    for slug in TRACKED_STATES:
        if new_state[slug] > 0:
            state_data[slug]["last_updated"] = TODAY_STR
            save_json(DATA_DIR / "states" / f"{slug}.json", state_data[slug])
    total_new = new_federal + sum(new_state.values())
    print(f"\nDone. {total_new} new entries added. Filtered: {stats}")

if __name__ == "__main__":
    run()
