"""
DR Sync Script - runs from repo root
Fetches live DR data from Jira and rebuilds index.html from template.html
"""

import json, os, requests
from datetime import datetime, timezone

JIRA_BASE  = os.environ["JIRA_BASE"]
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_TOKEN = os.environ["JIRA_TOKEN"]

FIELDS = [
    "summary","issuetype","project","reporter","description","status","assignee",
    "components","customfield_10376","customfield_10681","customfield_11439",
    "customfield_11770","customfield_11869","customfield_11935","customfield_12068",
    "fixVersions","issuelinks","labels","parent","priority",
    "created","updated","resolutiondate","comment"
]

FFT_FILTER = ('summary ~ "N208" OR summary ~ "208B" OR summary ~ "MLN" '
              'OR summary ~ "ZKMLN" OR text ~ "N208B" OR text ~ "ZKMLN" OR summary ~ "208"')

# Note: "Won't Fix" removed to avoid quote escaping issues - excluded via statusCategory below
MPPT_JQL = 'project = MPPT AND issuetype = DR AND statusCategory != Done ORDER BY created DESC'
FFT_JQL  = f'project = FFT AND issuetype = DR AND statusCategory != Done AND ({FFT_FILTER}) ORDER BY created DESC'

QUERIES = {"MPPT": MPPT_JQL, "FFT": FFT_JQL}

# Closed DRs — minimal fields only, last 18 months, for burndown chart
CLOSED_FIELDS = ["summary", "created", "resolutiondate", "status", "project", "issuetype",
                 "customfield_11935", "customfield_12068"]
MPPT_CLOSED_JQL = ('project = MPPT AND issuetype = DR AND statusCategory = Done '
                   'AND resolutiondate >= "2026-03-01" ORDER BY resolutiondate DESC')
FFT_CLOSED_JQL  = (f'project = FFT AND issuetype = DR AND statusCategory = Done '
                   f'AND ({FFT_FILTER}) AND resolutiondate >= "2026-03-01" ORDER BY resolutiondate DESC')
QUERIES_CLOSED  = {"MPPT": MPPT_CLOSED_JQL, "FFT": FFT_CLOSED_JQL}

def jira_search(jql, fields, start=0, max_results=100):
    url = f"{JIRA_BASE}/rest/api/3/search/jql"
    r = requests.get(
        url,
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        headers={"Accept": "application/json"},
        params={"jql": jql, "fields": ",".join(fields),
                "startAt": start, "maxResults": max_results}
    )
    print(f"  HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  Response: {r.text[:500]}")
    r.raise_for_status()
    return r.json()

def fetch_all(jql, fields):
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
    template_path = os.path.join(root, "template.html")
    output_path   = os.path.join(root, "index.html")

    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    timestamp   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data_json   = json.dumps(all_rows,    ensure_ascii=False, separators=(",", ":"))
    closed_json = json.dumps(closed_rows, ensure_ascii=False, separators=(",", ":"))

    html = html.replace("__DR_DATA_PLACEHOLDER__",     data_json)
    html = html.replace("__CLOSED_DATA_PLACEHOLDER__", closed_json)
    html = html.replace("__SYNC_TIMESTAMP_PLACEHOLDER__", timestamp)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"index.html rebuilt - {len(all_rows)} open + {len(closed_rows)} closed, {timestamp}")

if __name__ == "__main__":
    main()
