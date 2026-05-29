"""
DR Sync Script - runs from repo root
Fetches live DR data from Jira and rebuilds index.html from template.html.
Also syncs progress metrics from Google Sheets to progress-snapshot.json.
"""

import json, os, requests
from datetime import datetime, timezone

JIRA_BASE  = os.environ["JIRA_BASE"]
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_TOKEN = os.environ["JIRA_TOKEN"]

FIELDS = [
    "summary","issuetype","project","reporter","description","status","assignee",
    "components","customfield_10123","customfield_10376","customfield_10681","customfield_11439",
    "customfield_11770","customfield_11869","customfield_11935","customfield_12068",
    "fixVersions","issuelinks","labels","parent","priority",
    "created","updated","resolutiondate","comment",
    "customfield_11176","customfield_12607"
]

# All DRs from MPPT — no aircraft or type filter
MPPT_JQL = 'project = MPPT AND issuetype = DR AND statusCategory != Done ORDER BY created DESC'
QUERIES = {"MPPT": MPPT_JQL}

# Closed DRs — minimal fields only, last 18 months, for burndown chart
CLOSED_FIELDS = ["summary", "created", "resolutiondate", "status", "project", "issuetype",
                 "customfield_10123", "customfield_11935", "customfield_12068"]
MPPT_CLOSED_JQL = ('project = MPPT AND issuetype = DR AND statusCategory = Done '
                   'AND resolutiondate >= "2026-03-01" ORDER BY resolutiondate DESC')
QUERIES_CLOSED  = {"MPPT": MPPT_CLOSED_JQL}

def jira_search_page(jql, fields, next_page_token=None, max_results=100):
    """Fetch one page from the Jira Cloud search/jql endpoint (cursor-based pagination)."""
    url = f"{JIRA_BASE}/rest/api/3/search/jql"
    params = {"jql": jql, "fields": ",".join(fields), "maxResults": max_results}
    if next_page_token:
        params["nextPageToken"] = next_page_token
    r = requests.get(
        url,
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        headers={"Accept": "application/json"},
        params=params,
        timeout=60
    )
    print(f"  HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  Response: {r.text[:500]}")
    r.raise_for_status()
    return r.json()

def fetch_all(jql, fields):
    """Fetch all results using cursor-based pagination (nextPageToken)."""
    issues = []
    next_page_token = None
    page = 0
    while True:
        page += 1
        data = jira_search_page(jql, fields, next_page_token=next_page_token)
        batch = data.get("issues", [])
        issues.extend(batch)
        next_page_token = data.get("nextPageToken")
        print(f"  Page {page}: {len(batch)} issues fetched (running total: {len(issues)})")
        if not batch or not next_page_token:
            break
    return issues

def adf_to_text(node):
    if not node: return ""
    if isinstance(node, str): return node
    texts = []
    def recurse(n):
        if isinstance(n, dict):
            if n.get("type") == "text": texts.append(n.get("text", ""))
            for v in n.values():
                if isinstance(v, (dict, list)): recurse(v)
        elif isinstance(n, list):
            for item in n: recurse(item)
    recurse(node)
    return " ".join(texts).strip()

def get_select(cf):
    if not cf: return ""
    return cf.get("value", "") if isinstance(cf, dict) else str(cf)

def get_user(cf): return cf.get("displayName", "") if cf else ""

def get_multi(cf_list):
    if not cf_list: return ""
    return ", ".join(c.get("name", "") if isinstance(c, dict) else str(c) for c in cf_list)

def get_issue_links(links):
    if not links: return ""
    parts = []
    for lnk in links:
        lt = lnk.get("type", {}).get("name", "")
        for direction in ["inwardIssue", "outwardIssue"]:
            issue = lnk.get(direction, {})
            if issue:
                status = issue.get("fields", {}).get("status", {}).get("name", "")
                parts.append(f"{lt} {issue.get('key', '')} ({status})")
    return "; ".join(parts)

def parse_issue(i):
    f = i["fields"]
    comment_obj = f.get("comment") or {}
    comments = comment_obj.get("comments", [])
    last_comment = adf_to_text(comments[-1].get("body", ""))[:300] if comments else ""
    return {
        "Key":                          i["key"],
        "Project":                      f.get("project", {}).get("key", ""),
        "Summary":                      f.get("summary", ""),
        "Issue Type":                   f.get("issuetype", {}).get("name", "") if f.get("issuetype") else "",
        "Status":                       f.get("status", {}).get("name", "") if f.get("status") else "",
        "DR Type":                      get_select(f.get("customfield_11935")),
        "Functional Team (System)":     get_select(f.get("customfield_12068")),
        "Priority":                     f.get("priority", {}).get("name", "") if f.get("priority") else "",
        "Assignee":                     get_user(f.get("assignee")),
        "Reporter":                     get_user(f.get("reporter")),
        "Components":                   get_multi(f.get("components", [])),
        "Labels":                       ", ".join(f.get("labels", [])),
        "Fix Versions":                 get_multi(f.get("fixVersions", [])),
        "Linked Issues":                get_issue_links(f.get("issuelinks", [])),
        "Parent":                       f.get("parent", {}).get("key", "") if f.get("parent") else "",
        "Temp Mitigations & SIIs":      adf_to_text(f.get("customfield_10376")),
        "Safety Justification":         adf_to_text(f.get("customfield_10681")),
        "System Components":            adf_to_text(f.get("customfield_11439")),
        "Flight Deck Effect":           adf_to_text(f.get("customfield_11770")),
        "Safe for Operation Rationale": get_select(f.get("customfield_11869")),
        "Description":                  adf_to_text(f.get("description"))[:500],
        "Comment Count":                len(comments),
        "Last Comment":                 last_comment,
        "Created":                      (f.get("created", "") or "")[:10],
        "Updated":                      (f.get("updated", "") or "")[:10],
        "Resolution Date":              (f.get("resolutiondate", "") or "")[:10],
        "URL":                          f"https://merlinlabs.atlassian.net/browse/{i['key']}",
        "Affected Aircraft":            ", ".join(opt.get("value","") for opt in (f.get("customfield_10123") or []) if isinstance(opt, dict)),
        "Functional System":            get_select(f.get("customfield_11176")),
        "SFHA Function":                get_select(f.get("customfield_12607")),
    }

def parse_closed(i):
    f = i["fields"]
    return {
        "Key":             i["key"],
        "Project":         f.get("project", {}).get("key", ""),
        "Created":         (f.get("created", "") or "")[:10],
        "ResolutionDate":  (f.get("resolutiondate", "") or "")[:10],
        "DR Type":         get_select(f.get("customfield_11935")),
        "Functional Team": get_select(f.get("customfield_12068")),
    }

def main():
    all_rows = []
    for project, jql in QUERIES.items():
        print(f"\nFetching {project}...")
        issues = fetch_all(jql, FIELDS)
        rows = [parse_issue(i) for i in issues]
        rows.sort(key=lambda r: -int(r["Key"].split("-")[1]))
        all_rows.extend(rows)
        print(f"  -> {len(rows)} {project} DRs")

    print(f"\nTotal open: {len(all_rows)} DRs")

    closed_rows = []
    for project, jql in QUERIES_CLOSED.items():
        print(f"\nFetching closed {project}...")
        issues = fetch_all(jql, CLOSED_FIELDS)
        rows = [parse_closed(i) for i in issues]
        closed_rows.extend(rows)
        print(f"  -> {len(rows)} closed {project} DRs")

    print(f"Total closed (18 mo): {len(closed_rows)} DRs")

    root = os.path.dirname(os.path.abspath(__file__))
    timestamp   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data_json   = json.dumps(all_rows,    ensure_ascii=False, separators=(",", ":"))
    closed_json = json.dumps(closed_rows, ensure_ascii=False, separators=(",", ":"))

    # ── Main dashboard ──────────────────────────────────────────────────────
    template_path = os.path.join(root, "template.html")
    output_path   = os.path.join(root, "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__DR_DATA_PLACEHOLDER__",      data_json)
    html = html.replace("__CLOSED_DATA_PLACEHOLDER__",  closed_json)
    html = html.replace("__SYNC_TIMESTAMP_PLACEHOLDER__", timestamp)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"index.html rebuilt - {len(all_rows)} open + {len(closed_rows)} closed, {timestamp}")

    # ── Avidyne-only dashboard ───────────────────────────────────────────────
    # Reuse data_json / closed_json already serialised above — no re-encode needed.
    # The Avidyne chip filter is pre-enabled in the template UI so the supplier
    # only sees Avidyne-tagged DRs without needing to interact.
    avi_template_path = os.path.join(root, "template-avidyne.html")
    avi_output_path   = os.path.join(root, "avidyne.html")
    print(f"\nAvidyne template path: {avi_template_path}")
    print(f"  exists: {os.path.exists(avi_template_path)}")
    if os.path.exists(avi_template_path):
        try:
            with open(avi_template_path, "r", encoding="utf-8") as f:
                avi_html = f.read()
            avi_html = avi_html.replace("__DR_DATA_PLACEHOLDER__",     data_json)
            avi_html = avi_html.replace("__CLOSED_DATA_PLACEHOLDER__", closed_json)
            avi_html = avi_html.replace("__SYNC_TIMESTAMP_PLACEHOLDER__", timestamp)
            with open(avi_output_path, "w", encoding="utf-8") as f:
                f.write(avi_html)
            print(f"avidyne.html rebuilt - {len(all_rows)} DRs, {timestamp}")
        except Exception as e:
            print(f"ERROR building avidyne.html: {e}")
    else:
        print("template-avidyne.html not found — skipping Avidyne dashboard")

# ── Progress Metrics Sync ─────────────────────────────────────────────────────
PROGRESS_SHEET_ID = '1axaAXoiObpBw150OyQi_iee6_oUMoHnQA3BLXqomdfA'
PROGRESS_GID      = 289464578
TARGET_CAPS       = ['LPV', 'TO', 'TD', 'ACS']

def sync_progress_metrics():
    sa_key_str = os.environ.get('GOOGLE_SA_KEY', '')
    if not sa_key_str:
        print("\nGOOGLE_SA_KEY not set — skipping progress metrics sync")
        return

    print("\nSyncing progress metrics from Google Sheets...")
    try:
        import gspread
        gc = gspread.service_account_from_dict(json.loads(sa_key_str))
        sh = gc.open_by_key(PROGRESS_SHEET_ID)
        ws = sh.get_worksheet_by_id(PROGRESS_GID)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"  Error reading sheet: {e}")
        return

    # Find the header row containing "Capability" and "Total Points"
    header_idx = -1
    for i, row in enumerate(rows):
        stripped = [str(c).strip() for c in row]
        if 'Capability' in stripped and 'Total Points' in stripped:
            header_idx = i
            break
    if header_idx == -1:
        print("  Could not find header row")
        return

    headers = [str(c).strip() for c in rows[header_idx]]

    def col(name):
        try:
            return headers.index(name)
        except ValueError:
            return -1

    C = {
        'cap':       col('Capability'),
        'total':     col('Total Points'),
        'flown':     col('Points Flown'),
        'accepted':  col('Points Accepted'),
        'notNeeded': col('Points Not Needed'),
        'reflies':   col('Reflies To Be Flown'),
        'pending':   col('Pending Review'),
        'blocked':   col('Blocked Test Points'),
        'leftToFly': col('Points Left to Fly'),
        'pct':       col('Percent Completed'),
    }

    def num(v):
        try:
            return int(float(str(v).replace(',', '') or '0'))
        except (ValueError, TypeError):
            return 0

    def parse_pct(v):
        s = str(v).strip()
        if not s:
            return 0.0
        if s.endswith('%'):
            return round(float(s[:-1]), 2)
        try:
            f = float(s)
            return round(f * 100 if f <= 1 else f, 2)
        except ValueError:
            return 0.0

    capabilities = []
    for row in rows[header_idx + 1:]:
        if C['cap'] < 0 or C['cap'] >= len(row):
            continue
        cap_name = str(row[C['cap']]).strip()
        if cap_name not in TARGET_CAPS:
            continue
        capabilities.append({
            'name':       cap_name,
            'total':      num(row[C['total']]),
            'flown':      num(row[C['flown']]),
            'accepted':   num(row[C['accepted']]),
            'notNeeded':  num(row[C['notNeeded']]),
            'reflies':    num(row[C['reflies']]),
            'pending':    num(row[C['pending']]),
            'blocked':    num(row[C['blocked']]),
            'leftToFly':  num(row[C['leftToFly']]),
            'pct':        parse_pct(row[C['pct']]),
        })
        if len(capabilities) == len(TARGET_CAPS):
            break

    if not capabilities:
        print("  No capability rows found")
        return

    def ssum(k):
        return sum(c[k] for c in capabilities)

    total_pts      = ssum('total')
    total_not_needed = ssum('notNeeded')
    total_accepted = ssum('accepted')
    total = {
        'name':       'Total',
        'total':      total_pts,
        'flown':      ssum('flown'),
        'accepted':   total_accepted,
        'notNeeded':  total_not_needed,
        'reflies':    ssum('reflies'),
        'pending':    ssum('pending'),
        'blocked':    ssum('blocked'),
        'leftToFly':  ssum('leftToFly'),
        'pct':        round(total_accepted / (total_pts - total_not_needed) * 100, 2)
                      if (total_pts - total_not_needed) > 0 else 0,
    }

    snapshot = {
        'lastUpdated':  datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'capabilities': capabilities,
        'total':        total,
    }

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'progress-snapshot.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, separators=(',', ':'))

    print(f"  Wrote progress-snapshot.json — {len(capabilities)} caps, "
          f"{total_accepted}/{total_pts - total_not_needed} accepted ({total['pct']}%)")


if __name__ == "__main__":
    main()
    sync_progress_metrics()
