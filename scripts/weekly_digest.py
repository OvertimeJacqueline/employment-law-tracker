#!/usr/bin/env python3
"""
weekly_digest.py â Sends a Monday morning employment law digest email.

Reads all JSON data files, organises them into four sections:
  â° Deadlines Coming Up   (next 90 days)
  ð New This Week         (updated in last 7 days)
  ð« Repealed / Blocked
  ð On the Horizon        (proposed)

For manually-curated entries: shows the compliance action checklist.
For auto-detected RSS entries: redirects reader to the source article.

Required GitHub Secrets:
  GMAIL_CLIENT_ID
  GMAIL_CLIENT_SECRET
  GMAIL_REFRESH_TOKEN
  DIGEST_RECIPIENTS   â comma-separated, e.g. "alice@co.com,bob@co.com"
"""

import json, os, base64, sys
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


# ââ Colours & labels âââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

STATUS_COLOR = {
    "upcoming": "#f59e0b",
    "recent":   "#3b82f6",
    "repealed": "#ef4444",
    "proposed": "#8b5cf6",
}
STATUS_LABEL = {
    "upcoming": "UPCOMING DEADLINE",
    "recent":   "RECENTLY CHANGED",
    "repealed": "REPEALED / BLOCKED",
    "proposed": "PROPOSED",
}
PRIORITY_SLUGS = {"california", "new-york", "georgia", "illinois"}
SITE_URL = "https://overtimejacqueline.github.io/employment-law-tracker/"


# ââ Data helpers ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def load_all_laws():
    root = Path(__file__).parent.parent / "data"
    laws = []

    fed = root / "federal.json"
    if fed.exists():
        for law in json.loads(fed.read_text()).get("laws", []):
            law["_jurisdiction"] = "Federal"
            law["_priority"]     = False
            laws.append(law)

    states_dir = root / "states"
    if states_dir.exists():
        for f in sorted(states_dir.glob("*.json")):
            slug  = f.stem
            label = slug.replace("-", " ").title()
            for law in json.loads(f.read_text()).get("laws", []):
                law["_jurisdiction"] = label
                law["_priority"]     = slug in PRIORITY_SLUGS
                laws.append(law)

    return laws


def categorize(laws):
    today    = date.today()
    week_ago = today - timedelta(days=7)
    in_90    = today + timedelta(days=90)

    upcoming, new_week, repealed, proposed = [], [], [], []
    seen_upcoming = set()

    for law in laws:
        status  = law.get("status", "")
        updated = parse_date(law.get("last_updated"))
        dl      = parse_date(law.get("deadline")) or parse_date(law.get("effective_date"))
        lid     = law.get("id", "")

        if status == "upcoming" and dl and today <= dl <= in_90:
            law["_days_until"] = (dl - today).days
            upcoming.append(law)
            seen_upcoming.add(lid)

        if updated and updated >= week_ago and status in ("recent", "upcoming") and lid not in seen_upcoming:
            new_week.append(law)

        if status == "repealed":
            repealed.append(law)

        if status == "proposed":
            proposed.append(law)

    upcoming.sort(key=lambda x: x.get("_days_until", 999))

    def priority_key(law):
        if law.get("_priority"):      return 0
        if law["_jurisdiction"] == "Federal": return 1
        return 2

    new_week.sort(key=priority_key)
    return upcoming, new_week, repealed, proposed


# ââ HTML helpers ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def h(text):
    """Minimal HTML escaping."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def days_badge(days):
    if days <= 30:
        color, icon = "#dc2626", "â ï¸"
    elif days <= 60:
        color, icon = "#d97706", "ð"
    else:
        color, icon = "#6b7280", "ð"
    return (f'<span style="color:{color};font-weight:700;">'
            f'{icon} {days} day{"s" if days != 1 else ""} away</span>')


def law_card(law, show_dl=False):
    status     = law.get("status", "recent")
    color      = STATUS_COLOR.get(status, "#3b82f6")
    badge      = STATUS_LABEL.get(status, status.upper())
    jur        = h(law.get("_jurisdiction", ""))
    priority   = law.get("_priority", False)
    is_auto    = law.get("_auto_generated", False)
    title      = h(law.get("title", ""))
    summary    = h(law.get("summary", "")[:450] + ("â¦" if len(law.get("summary","")) > 450 else ""))
    source_url = law.get("source_url", "")
    dl         = parse_date(law.get("deadline") or law.get("effective_date"))
    actions    = [a for a in law.get("compliance_actions", [])
                  if not a.startswith("â ï¸") and not a.startswith("Auto-detected")]

    # ââ status + jurisdiction badges
    priority_badge = (
        '<td style="padding-left:6px;vertical-align:middle;">'
        '<span style="background:#fef3c7;color:#92400e;padding:2px 8px;'
        'border-radius:10px;font-size:11px;font-weight:700;">â PRIORITY</span></td>'
        if priority else ""
    )
    badges = f"""
      <table cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
        <tr>
          <td style="vertical-align:middle;">
            <span style="background:{color};color:#fff;padding:3px 10px;
              border-radius:10px;font-size:11px;font-weight:700;letter-spacing:.4px;">{badge}</span>
          </td>
          <td style="padding-left:6px;vertical-align:middle;">
            <span style="background:#f3f4f6;color:#374151;padding:3px 10px;
              border-radius:10px;font-size:11px;font-weight:600;">{jur}</span>
          </td>
          {priority_badge}
        </tr>
      </table>"""

    # ââ deadline line
    dl_html = ""
    if show_dl and dl:
        days = (dl - date.today()).days
        dl_html = (f'<p style="margin:4px 0 8px;font-size:13px;">'
                   f'{days_badge(days)} &nbsp;Â·&nbsp; '
                   f'Effective {dl.strftime("%B %-d, %Y")}</p>')

    # ââ compliance block
    if is_auto or not actions:
        if source_url:
            compliance = f"""
      <table cellpadding="0" cellspacing="0" width="100%"
             style="margin-top:12px;background:#fefce8;border-left:3px solid #f59e0b;border-radius:0 4px 4px 0;">
        <tr><td style="padding:10px 14px;font-size:13px;color:#78350f;line-height:1.6;">
          This item was auto-detected from a law firm news feed and has not yet been
          manually reviewed. <strong>Review the source article before taking any
          compliance action:</strong><br>
          <a href="{source_url}" style="color:#1d4ed8;word-break:break-all;">{h(source_url)}</a>
        </td></tr>
      </table>"""
        else:
            compliance = ""
    else:
        items = "".join(f'<li style="margin-bottom:5px;">{h(a)}</li>' for a in actions)
        compliance = f"""
      <div style="margin-top:12px;">
        <p style="margin:0 0 6px;font-size:11px;font-weight:700;color:#374151;
                  text-transform:uppercase;letter-spacing:.5px;">Required Compliance Actions</p>
        <ul style="margin:0;padding-left:18px;color:#374151;font-size:13px;line-height:1.7;">
          {items}
        </ul>
      </div>"""

    # ââ read more link
    read_more = (f'<a href="{source_url}" style="font-size:12px;color:#1d4ed8;'
                 f'text-decoration:none;font-weight:600;">Read full article â</a>'
                 if source_url else "")

    return f"""
  <table cellpadding="0" cellspacing="0" width="100%"
         style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;
                margin-bottom:14px;">
    <tr><td style="padding:20px 22px;">
      {badges}
      <h3 style="margin:0 0 6px;font-size:15px;font-weight:700;color:#111827;line-height:1.4;">{title}</h3>
      {dl_html}
      <p style="margin:0;font-size:13px;color:#4b5563;line-height:1.65;">{summary}</p>
      {compliance}
      <table cellpadding="0" cellspacing="0" width="100%" style="margin-top:14px;border-top:1px solid #f3f4f6;">
        <tr><td style="padding-top:12px;">{read_more}</td></tr>
      </table>
    </td></tr>
  </table>"""


def section(title, icon, laws, show_dl=False, empty_msg=None):
    if not laws and not empty_msg:
        return ""
    cards = "".join(law_card(l, show_dl) for l in laws)
    empty = (f'<p style="color:#6b7280;font-size:14px;font-style:italic;'
             f'padding:12px 0;">{empty_msg}</p>' if not laws and empty_msg else "")
    return f"""
  <table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:36px;">
    <tr><td>
      <h2 style="margin:0 0 14px;font-size:18px;font-weight:700;color:#111827;
                 padding-bottom:10px;border-bottom:2px solid #e5e7eb;">
        {icon}&nbsp; {title}
      </h2>
      {cards}{empty}
    </td></tr>
  </table>"""


# ââ Full email ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def build_html(upcoming, new_week, repealed, proposed, week_label):
    n_updates  = len(new_week)
    n_deadlines = len(upcoming)

    body = (
        section("Deadlines Coming Up", "â°", upcoming, show_dl=True,
                empty_msg="No compliance deadlines in the next 90 days. â")
        + section("New This Week", "ð", new_week,
                  empty_msg="No new updates this week.")
        + (section("Repealed or Blocked", "ð«", repealed) if repealed else "")
        + (section("On the Horizon", "ð", proposed) if proposed else "")
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Employment Law Digest â {week_label}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,sans-serif;">

  <!-- ââ Header ââ -->
  <table cellpadding="0" cellspacing="0" width="100%"
         style="background:#1a2744;">
    <tr><td style="padding:28px 40px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        <tr>
          <td style="vertical-align:middle;">
            <p style="margin:0 0 3px;font-size:11px;color:#94a3b8;
                      font-weight:600;letter-spacing:1px;text-transform:uppercase;">
              Overtime &nbsp;|&nbsp; Employment Law
            </p>
            <p style="margin:0;font-size:26px;font-weight:800;color:#ffffff;">
              Employment Law Digest
            </p>
            <p style="margin:4px 0 0;font-size:13px;color:#94a3b8;">
              Week of {week_label}
            </p>
          </td>
          <td style="text-align:right;vertical-align:middle;">
            <span style="background:#f59e0b;color:#1a2744;padding:8px 16px;
                         border-radius:6px;font-size:13px;font-weight:800;
                         display:inline-block;">
              {n_updates} update{"s" if n_updates != 1 else ""} this week
            </span>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>

  <!-- ââ Stats bar ââ -->
  <table cellpadding="0" cellspacing="0" width="100%"
         style="background:#1e3a5f;">
    <tr><td style="padding:12px 40px;font-size:13px;color:#cbd5e1;">
      <span style="color:#fbbf24;font-weight:700;">{n_deadlines}</span>
      &nbsp;upcoming deadline{"s" if n_deadlines != 1 else ""}
      &nbsp;&nbsp;Â·&nbsp;&nbsp;
      <span style="color:#60a5fa;font-weight:700;">{n_updates}</span>
      &nbsp;new / updated
      &nbsp;&nbsp;Â·&nbsp;&nbsp;
      <span style="color:#f87171;font-weight:700;">{len(repealed)}</span>
      &nbsp;repealed
      &nbsp;&nbsp;Â·&nbsp;&nbsp;
      <span style="color:#c4b5fd;font-weight:700;">{len(proposed)}</span>
      &nbsp;proposed
    </td></tr>
  </table>

  <!-- ââ Body ââ -->
  <table cellpadding="0" cellspacing="0" width="100%">
    <tr><td>
      <table cellpadding="0" cellspacing="0" width="100%"
             style="max-width:700px;margin:0 auto;">
        <tr><td style="padding:32px 24px;">
          {body}

          <!-- ââ CTA ââ -->
          <table cellpadding="0" cellspacing="0" width="100%"
                 style="background:#1a2744;border-radius:10px;margin-top:8px;">
            <tr><td style="padding:28px 32px;text-align:center;">
              <p style="margin:0 0 16px;font-size:14px;color:#cbd5e1;line-height:1.6;">
                View all tracked laws, filter by state, and access full compliance
                checklists on the tracker.
              </p>
              <a href="{SITE_URL}"
                 style="background:#f59e0b;color:#1a2744;padding:13px 30px;
                        border-radius:6px;text-decoration:none;font-weight:800;
                        font-size:14px;display:inline-block;">
                View Full Employment Law Tracker â
              </a>
            </td></tr>
          </table>

          <!-- ââ Footer ââ -->
          <p style="margin:24px 0 0;text-align:center;color:#9ca3af;
                    font-size:12px;line-height:1.7;">
            Auto-detected RSS entries are flagged for review and have not been
            manually verified.<br>
            Always confirm with employment counsel before taking compliance action.<br><br>
            <span style="color:#d1d5db;">
              Overtime Sports &nbsp;Â·&nbsp; Employment Law Tracker
              &nbsp;Â·&nbsp; Sent every Monday morning
            </span>
          </p>

        </td></tr>
      </table>
    </td></tr>
  </table>

</body>
</html>"""


# ââ Send ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def get_gmail_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds)


def send(html_body, week_label, recipients):
    service = get_gmail_service()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Employment Law Digest â Week of {week_label}"
    msg["From"]    = "jacqueline@itsovertime.com"
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"â Digest sent to: {', '.join(recipients)}")


# ââ Entry point âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def run():
    required = ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
                "GMAIL_REFRESH_TOKEN", "DIGEST_RECIPIENTS"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Skipping digest â missing env vars: {', '.join(missing)}")
        return

    recipients = [r.strip() for r in os.environ["DIGEST_RECIPIENTS"].split(",") if r.strip()]
    if not recipients:
        print("Skipping digest â DIGEST_RECIPIENTS is empty")
        return

    laws = load_all_laws()
    upcoming, new_week, repealed, proposed = categorize(laws)
    week_label = date.today().strftime("%B %-d, %Y")
    html = build_html(upcoming, new_week, repealed, proposed, week_label)
    send(html, week_label, recipients)


if __name__ == "__main__":
    run()
