"""
Employment Law Tracker — Monthly Google Sheet State Checker
============================================================
Reads the "Active States for Employees" Google Sheet and compares
against the currently tracked states. Sends an alert (printed to console /
GitHub Actions log) if states have been added or removed.

Run monthly via GitHub Actions.

Requirements:
    pip install gspread google-auth

Setup:
    1. Create a Google Service Account in Google Cloud Console
    2. Share the spreadsheet with the service account email
    3. Download the service account JSON key
    4. Set the GOOGLE_CREDENTIALS_JSON environment variable to the contents of the key file
    5. Set the SPREADSHEET_ID environment variable to your spreadsheet ID

Usage:
    SPREADSHEET_ID="1er3jynzBjFBEm91_P0hR5oldbBc6NZb7UP_uqKgqlmM" python scripts/check_states.py
"""

import json
import os
import sys
from pathlib import Path

# State abbreviation → slug mapping
ABBREV_TO_SLUG = {
    "AZ": "arizona",
    "CA": "california",
    "CO": "colorado",
    "CT": "connecticut",
    "FL": "florida",
    "GA": "georgia",
    "IL": "illinois",
    "IN": "indiana",
    "KY": "kentucky",
    "MA": "massachusetts",
    "MI": "michigan",
    "MN": "minnesota",
    "NJ": "new-jersey",
    "NY": "new-york",
    "NC": "north-carolina",
    "OH": "ohio",
    "PA": "pennsylvania",
    "TN": "tennessee",
    "TX": "texas",
    "UT": "utah",
    "VA": "virginia",
    "WA": "washington",
    # Add more as needed
    "AL": "alabama", "AK": "alaska", "AR": "arkansas",
    "DE": "delaware", "HI": "hawaii", "ID": "idaho",
    "IA": "iowa", "KS": "kansas", "LA": "louisiana",
    "ME": "maine", "MD": "maryland", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska",
    "NV": "nevada", "NH": "new-hampshire", "NM": "new-mexico",
    "ND": "north-dakota", "OK": "oklahoma", "OR": "oregon",
    "RI": "rhode-island", "SC": "south-carolina", "SD": "south-dakota",
    "VT": "vermont", "WV": "west-virginia", "WI": "wisconsin", "WY": "wyoming",
    "DC": "district-of-columbia",
}

DATA_DIR   = Path(__file__).parent.parent / "data" / "states"
SIDEBAR_JS = Path(__file__).parent.parent / "index.html"

# Current tracked states (matches what's in the sidebar)
CURRENT_TRACKED = {
    "arizona", "california", "colorado", "connecticut", "florida",
    "georgia", "illinois", "indiana", "kentucky", "massachusetts",
    "michigan", "minnesota", "new-jersey", "new-york", "north-carolina",
    "ohio", "pennsylvania", "tennessee", "texas", "utah",
    "virginia", "washington",
}


def fetch_states_from_sheet(spreadsheet_id: str) -> set[str]:
    """Fetch state abbreviations from the Google Sheet and convert to slugs."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("ERROR: Missing dependencies. Run: pip install gspread google-auth")
        sys.exit(1)

    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        print("ERROR: GOOGLE_CREDENTIALS_JSON environment variable not set.")
        print("See scripts/check_states.py header for setup instructions.")
        sys.exit(1)

    try:
        creds_dict = json.loads(creds_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(spreadsheet_id).sheet1
        values = sheet.get_all_values()
    except Exception as e:
        print(f"ERROR: Could not read Google Sheet: {e}")
        sys.exit(1)

    state_slugs = set()
    for row in values:
        for cell in row:
            cell = cell.strip().upper()
            if cell in ABBREV_TO_SLUG:
                state_slugs.add(ABBREV_TO_SLUG[cell])
    return state_slugs


def create_empty_state_json(slug: str):
    """Create a blank JSON file for a newly added state."""
    slug_to_name = {v: k for k, v in ABBREV_TO_SLUF.items()}
    state_name = slug.replace("-", " ").title()
    data = {
        "last_updated": "pending",
        "state": state_name,
        "laws": []
    }
    path = DATA_DIR / f"{slug}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Created empty data file: {path}")


def check(spreadsheet_id: str):
    print("\n=== Monthly State List Check ===")
    print(f"Spreadsheet ID: {spreadsheet_id}")

    sheet_states   = fetch_states_from_sheet(spreadsheet_id)
    current_states = CURRENT_TRACKED

    added   = sheet_states - current_states
    removed = current_states - sheet_states

    if not added and not removed:
        print("\n✅ No changes detected. State list is up to date.")
        return

    if added:
        print(f"\n🆕 STATES ADDED ({len(added)}):")
        for s in sorted(added):
            print(f"  + {s}")
            create_empty_state_json(s)
        print("\n  ACTION REQUIRED: Add these states to the sidebar in index.html")
        print("  and update TRACKED_STATES in scripts/scraper.py and CURRENT_TRACKED in this file.")

    if removed:
        print(f"\n🗑️  STATES REMOVED ({len(removed)}):")
        for s in sorted(removed):
            print(f"  - {s}")
        print("\n  ACTION REQUIRED: Remove these states from the sidebar in index.html")
        print("  and update TRACKED_STATES in scripts/scraper.py and CURRENT_TRACKED in this file.")

    # Exit with error code so GitHub Actions flags this as needing attention
    sys.exit(1)


if __name__ == "__main__":
    spreadsheet_id = os.environ.get(
        "SPREADSHEET_ID", "1er3jynzBjFBEm91_P0hR5oldbBc6NZb7UP_uqKgqlmM"
    )
    check(spreadsheet_id)
