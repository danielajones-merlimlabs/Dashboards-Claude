"""
DR Sync Script
Fetches live DR data from Jira and rebuilds index.html from template.html.
Runs daily via GitHub Actions, or manually with:
  JIRA_EMAIL=you@merlinlabs.com JIRA_TOKEN=your_token python scripts/sync.py
"""

import json, os, re, requests
from datetime import datetime, timezone

# ── CONFIG ────────────────────────────────────────────────────────────────────
JIRA_BASE  = os.environ["JIRA_BASE"]          # https://merlinlabs.atlassian.net
JIRA_EMAIL = os.environ["JIRA_EMAIL"]         # your Atlassian account email
JIRA_TOKEN = os.environ["JIRA_TOKEN"]         # Jira API token (from id.atlassian.com)

EXCLUDE_STATUSES = ["Done", "Closed", "Won't Fix", "Duplicate"]

FIELDS = [
    "summary","issuetype","project","reporter","description","status","assignee",
    "components","customfield_10376","customfield_10681","customfield_11439",
    "customfield_11770","customfield_11869","customfield_11935","customfield_12068",
    "fixVersions","issuelinks","labels","parent","priority",
    "created","updated","resolutiondate","comment"
]

QUERIES = {
    "MPPT": (
        'project = MPPT AND issuetype = DR '
        'AND status NOT IN ("Done","Closed","Won\'t Fix","Duplicate") '
        'ORDER BY created DESC'
    ),
    "FFT": (
        'project = FFT AND issuetype = DR '
        'AND status NOT IN ("Done","Closed","Won\'t Fix","Duplicate") '
        'AND (summary ~ "N208" OR summary ~ "208B" OR summary ~ "MLN" '
        '     OR summary ~ "ZKMLN" OR text ~ "N208B" OR text ~ "ZKMLN" OR summary ~ "208") '
        'ORDER BY created DESC'
    ),
}

# ── JIRA FETCH ────────────────────────────────────────────────────────────────
def jira_search(jql, fields, start=0, max_results=100):
    url = f"{JIRA_BASE}/rest/api/3/search"
    auth = (JIRA_EMAIL, JIRA_TOKEN)
    headers = {"Accept": "application/json"}
    params = {
        "jql": jql,
        "fields": ",".join(fields),
        "startAt": start,
        "maxResults": max_results,
    }
    r = requests.get(url, auth=auth, headers=headers, params=params)
    r.raise_for_status()
    return r.json()

def fetch_all(jql, fields):
    """Paginate through all results."""
    issues, start = [], 0
    while True:
        data = jira_search(jql, fields, start=start)
        batch = data.get("issues", [])
        issues.extend(batch)
        total = data.get("total", 0)
        start += len(batch)
        print(f"  Fetched {start}/{total}")
        if start >= total or not batch:
            break
    return issues

# ── FIELD PARSERS ─────────────────────────────────────────────────────────────
def adf_to_text(node):
    """Recursively extract plain text from Atlassian Document Format."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    texts = []
    def recurse(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                texts.append(n.get("text", ""))
            for v in n.values():
                if isinstance(v, (dict, list)):
                    recurse(v)
        elif isinstance(n, list):
            for item in n:
                recurse(item)
    recurse(node)
    return " ".join(texts).strip()

def get_select(cf):
    if not cf: return ""
    return cf.get("value", "") if isinstance(cf, dict) else str(cf)

def get_user(cf):
    return cf.get("displayName", "") if cf else ""

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
    }

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    all_rows = []

    for project, jql in QUERIES.items():
        print(f"\nFetching {project}...")
        issues = fetch_all(jql, FIELDS)
        rows = [parse_issue(i) for i in issues]
        # Sort newest first within each project
        rows.sort(key=lambda r: -int(r["Key"].split("-")[1]))
        all_rows.extend(rows)
        print(f"  → {len(rows)} {project} DRs")

    print(f"\nTotal: {len(all_rows)} DRs")

    # Build the updated index.html from template
    template_path = os.path.join(os.path.dirname(__file__), "..", "template.html")
    output_path   = os.path.join(os.path.dirname(__file__), "..", "index.html")

    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data_json = json.dumps(all_rows, ensure_ascii=False, separators=(",", ":"))

    html = html.replace("__DR_DATA_PLACEHOLDER__", data_json)
    html = html.replace("__SYNC_TIMESTAMP_PLACEHOLDER__", timestamp)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅  index.html rebuilt ({len(all_rows)} rows, {timestamp})")

if __name__ == "__main__":
    main()
