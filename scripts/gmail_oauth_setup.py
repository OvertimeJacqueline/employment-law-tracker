#!/usr/bin/env python3
"""
gmail_oauth_setup.py  —  Run this ONCE on your local machine.

It opens a browser so you can authorize Gmail access for the tracker,
then prints the three values you need to add as GitHub Secrets.

Usage:
  1. pip install google-auth-oauthlib
  2. python gmail_oauth_setup.py
  3. Copy the three printed values into your GitHub repo secrets.
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

# Paste your OAuth client credentials here (from Google Cloud Console)
# See the setup guide for how to get these.
CLIENT_CONFIG = {
    "installed": {
        "client_id":     "PASTE_YOUR_CLIENT_ID_HERE",
        "client_secret": "PASTE_YOUR_CLIENT_SECRET_HERE",
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     "https://oauth2.googleapis.com/token",
    }
}

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def main():
    flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n" + "="*60)
    print("SUCCESS! Add these three values as GitHub Secrets:")
    print("="*60)
    print(f"\nGMAIL_CLIENT_ID\n  {CLIENT_CONFIG['installed']['client_id']}")
    print(f"\nGMAIL_CLIENT_SECRET\n  {CLIENT_CONFIG['installed']['client_secret']}")
    print(f"\nGMAIL_REFRESH_TOKEN\n  {creds.refresh_token}")
    print("\n" + "="*60)
    print("GitHub Secrets page:")
    print("https://github.com/OvertimeJacqueline/employment-law-tracker/settings/secrets/actions")
    print("="*60 + "\n")

if __name__ == '__main__':
    main()
