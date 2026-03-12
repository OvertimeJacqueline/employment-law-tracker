#!/usr/bin/env python3
"""
mineral_email_parser.py

Reads unread "Law Alert" emails from Mineral (noreply@trustmineral.com) via
Gmail API, parses them, and adds entries to the appropriate state/federal JSON
files in data/.

Authentication uses a refresh token stored in GitHub Secrets:
  GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN

Run after scraper.py in the daily GitHub Actions workflow.
"""

import os
import json
import re
import base64
import hashlib
import datetime
from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(SCRIPT_DIR, '..', 'data')
TODAY      = datetime.date.today().isoformat()

# ── Mineral sender ─────────────────────────────────────────────────────────────
MINERAL_SENDER = 'noreply@trustmineral.com'

# ── States currently tracked by the site ──────────────────────────────────────
TRACKED_STATES = {
    'arizona', 'california', 'colorado', 'connecticut', 'florida',
    'georgia', 'illinois', 'indiana', 'kentucky', 'massachusetts',
    'michigan', 'minnesota', 'new-jersey', 'new-york', 'north-carolina',
    'ohio', 'pennsylvania', 'tennessee', 'texas', 'utah', 'virginia',
    'washington',
}

# ── Jurisdiction name → slug ───────────────────────────────────────────────────
STATE_SLUG_MAP = {
    'Federal': 'federal',
    'Alabama': 'alabama', 'Alaska': 'alaska', 'Arizona': 'arizona',
    'Arkansas': 'arkansas', 'California': 'california', 'Colorado': 'colorado',
    'Connecticut': 'connecticut', 'Delaware': 'delaware', 'Florida': 'florida',
    'Georgia': 'georgia', 'Hawaii': 'hawaii', 'Idaho': 'idaho',
    'Illinois': 'illinois', 'Indiana': 'indiana', 'Iowa': 'iowa',
    'Kansas': 'kansas', 'Kentucky': 'kentucky', 'Louisiana': 'louisiana',
    'Maine': 'maine', 'Maryland': 'maryland', 'Massachusetts': 'massachusetts',
    'Michigan': 'michigan', 'Minnesota': 'minnesota', 'Mississippi': 'mississippi',
    'Missouri': 'missouri', 'Montana': 'montana', 'Nebraska': 'nebraska',
    'Nevada': 'nevada', 'New Hampshire': 'new-hampshire',
    'New Jersey': 'new-jersey', 'New Mexico': 'new-mexico',
    'New York': 'new-york', 'North Carolina': 'north-carolina',
    'North Dakota': 'north-dakota', 'Ohio': 'ohio', 'Oklahoma': 'oklahoma',
    'Oregon': 'oregon', 'Pennsylvania': 'pennsylvania',
    'Rhode Island': 'rhode-island', 'South Carolina': 'south-carolina',
    'South Dakota': 'south-dakota', 'Tennessee': 'tennessee', 'Texas': 'texas',
    'Utah': 'utah', 'Vermont': 'vermont', 'Virginia': 'virginia',
    'Washington': 'washington', 'West Virginia': 'west-virginia',
    'Wisconsin': 'wisconsin', 'Wyoming': 'wyoming',
}

# ── Gmail auth ─────────────────────────────────────────────────────────────────

def get_gmail_service():
    """Build an authenticated Gmail API service from GitHub Secrets."""
    creds = Credentials(
        token=None,
        refresh_token=os.environ['GMAIL_REFRESH_TOKEN'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=os.environ['GMAIL_CLIENT_ID'],
        client_secret=os.environ['GMAIL_CLIENT_SECRET'],
        scopes=['https://www.googleapis.com/auth/gmail.modify'],
    )
    creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)

# ── Email fetching ─────────────────────────────────────────────────────────────

def get_unread_law_alerts(service):
    """Return list of message stubs for unread Mineral Law Alert emails."""
    query = f'from:{MINERAL_SENDER} subject:"Law Alert:" is:unread'
    result = service.users().messages().list(userId='me', q=query).execute()
    messages = result.get('messages', [])
    print(f"  Found {len(messages)} unread Mineral Law Alert email(s)")
    return messages


def _decode_b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='replace')


def get_email_parts(service, msg_id):
    """Fetch a message and return (subject, date_str, html_body)."""
    msg = service.users().messages().get(
        userId='me', id=msg_id, format='full'
    ).execute()

    headers = {h['name']: h['value'] for h in msg['payload']['headers']}
    subject  = headers.get('Subject', '')
    date_str = headers.get('Date', '')

    def find_html(part):
        if part.get('mimeType') == 'text/html':
            data = part.get('body', {}).get('data')
            if data:
                return _decode_b64(data)
        for sub in part.get('parts', []):
            result = find_html(sub)
            if result:
                return result
        return ''

    html_body = find_html(msg['payload'])
    return subject, date_str, html_body

# ── Parsing ────────────────────────────────────────────────────────────────────

def parse_subject(subject: str):
    """
    Parse 'Law Alert: Federal: EEO-1 Data Collection Now Open!'
    Returns (jurisdiction_name, title) or (None, None).
    """
    m = re.match(r'Law Alert:\s*(.+?):\s*(.+)', subject, re.IGNORECASE)
    if not m:
        return None, None
    return m.group(1).strip(), m.group(2).strip()


def parse_body(html_body: str, title: str):
    """
    Extract summary paragraphs and action items from HTML body.
    Returns (summary: str, action_items: list[str]).
    """
    soup = BeautifulSoup(html_body, 'html.parser')
    for tag in soup(['script', 'style', 'img']):
        tag.decompose()

    raw = soup.get_text(separator='\n', strip=True)
    lines = [l.strip() for l in raw.split('\n') if l.strip()]

    # Skip lines up to and including the title
    content_start = 0
    for i, line in enumerate(lines):
        if title.lower() in line.lower() and len(line) <= len(title) + 30:
            content_start = i + 1
            break
    lines = lines[content_start:]

    FOOTER_MARKERS = ['mineral, inc', 'unsubscribe', '©20', 'this email is intended',
                      'read more', '844.413']
    ACTION_MARKERS = {'action items', 'action item'}

    summary_parts, action_items = [], []
    in_actions = False

    for line in lines:
        lower = line.lower()
        if any(lower.startswith(m) for m in FOOTER_MARKERS):
            break
        if lower in ACTION_MARKERS:
            in_actions = True
            continue
        if line.startswith('http'):
            continue
        if in_actions:
            action_items.append(line)
        else:
            summary_parts.append(line)

    # Trim
    summary = ' '.join(summary_parts).strip()
    # Cap summary at ~600 chars naturally
    if len(summary) > 600:
        summary = summary[:597] + '...'

    # Clean action items
    action_items = [a for a in action_items if len(a) > 15 and not a.startswith('http')][:4]

    if not action_items:
        action_items = [
            'Review the Mineral Law Alert for full details and applicability',
            'Consult your employment counsel before taking compliance action',
        ]

    return summary, action_items


def parse_email_date(date_str: str) -> str:
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(date_str).date().isoformat()
    except Exception:
        return TODAY


def make_id(title: str) -> str:
    h = hashlib.md5(title.encode()).hexdigest()[:8]
    return f'min-{h}'

# ── JSON helpers ───────────────────────────────────────────────────────────────

def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')


def get_file_path(slug: str) -> str:
    if slug == 'federal':
        return os.path.join(DATA_DIR, 'federal.json')
    return os.path.join(DATA_DIR, 'states', f'{slug}.json')

# ── Main processing ────────────────────────────────────────────────────────────

def process_message(service, msg_id, subject, date_str, html_body) -> bool:
    """Parse one Law Alert email and write to the appropriate JSON file."""
    jurisdiction, title = parse_subject(subject)
    if not jurisdiction or not title:
        print(f"    Skipping (not a law alert): {subject}")
        return False

    slug = STATE_SLUG_MAP.get(jurisdiction)
    if not slug:
        print(f"    Unknown jurisdiction '{jurisdiction}' — skipping")
        return False
    if slug != 'federal' and slug not in TRACKED_STATES:
        print(f"    Untracked state '{slug}' — skipping")
        return False

    file_path = get_file_path(slug)
    if not os.path.exists(file_path):
        print(f"    JSON file not found: {file_path} — skipping")
        return False

    data = load_json(file_path)
    laws = data.get('laws', [])

    # Deduplicate by title
    existing_titles = {l.get('title', '').strip().lower() for l in laws}
    if title.strip().lower() in existing_titles:
        print(f"    Duplicate: '{title}' already in {slug}")
        _mark_read(service, msg_id)
        return False

    summary, action_items = parse_body(html_body, title)
    email_date = parse_email_date(date_str)

    compliance_actions = [
        '⚠️ This entry was auto-detected from a Mineral Law Alert email. '
        'Review the source article for full details.',
    ] + action_items

    entry = {
        'id':                      make_id(title),
        'title':                   title,
        'status':                  'recent',
        'effective_date':          None,
        'deadline':                None,
        'summary':                 summary,
        'applies_to_company':      True,
        'min_employee_threshold':  None,
        'employee_threshold_note': None,
        'compliance_actions':      compliance_actions,
        'source':                  'Mineral',
        'source_url':              'https://apps.trustmineral.com/hr-compliance/law-alerts',
        'tags':                    [slug],
        'momentum_level':          'medium',
        'repeal_notes':            None,
        'last_updated':            email_date,
        '_auto_generated':         True,
        '_source_type':            'mineral_email',
    }

    laws.append(entry)
    data['laws']         = laws
    data['last_updated'] = TODAY
    save_json(file_path, data)

    print(f"    ✓ Added '{title}' → {slug}")
    _mark_read(service, msg_id)
    return True


def _mark_read(service, msg_id):
    service.users().messages().modify(
        userId='me', id=msg_id,
        body={'removeLabelIds': ['UNREAD']}
    ).execute()


def run():
    print('\n=== Mineral Email Parser ===')

    required = ['GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN']
    missing  = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f'  Missing secrets: {", ".join(missing)} — skipping Mineral email parsing')
        return

    service  = get_gmail_service()
    messages = get_unread_law_alerts(service)

    if not messages:
        print('  No new Mineral Law Alerts to process.')
        return

    added = 0
    for stub in messages:
        msg_id = stub['id']
        subject, date_str, html_body = get_email_parts(service, msg_id)
        print(f'\n  Processing: {subject}')
        if process_message(service, msg_id, subject, date_str, html_body):
            added += 1

    print(f'\n=== Done: {added} new entr{"y" if added == 1 else "ies"} added ===\n')


if __name__ == '__main__':
    run()
