"""
bulk_push_jira.py — one-time bulk push of Functional System and SFHA Function
values from the dashboard shared KV store to the corresponding Jira custom fields.

customfield_11176 = Functional System
customfield_12607 = SFHA Function
"""

import json, os, sys, requests

JIRA_BASE  = os.environ["JIRA_BASE"]
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_TOKEN = os.environ["JIRA_TOKEN"]
WORKER_URL = "https://dr-sync-worker.daniela-jones.workers.dev"

FIELD_MAP = {
    "FuncSys":  "customfield_11176",   # Functional System
    "SfhaFunc": "customfield_12607",   # SFHA Function
}


def main():
    # ── 1. Fetch all shared data from the Worker KV store ──────────────────
    print("Fetching shared data from Worker KV...")
    r = requests.get(f"{WORKER_URL}?action=getAll", timeout=30)
    r.raise_for_status()
    rows = r.json().get("rows", [])
    print(f"  {len(rows)} total KV entries")

    # ── 2. Keep only rows that have at least one field to push ──────────────
    to_update = [
        row for row in rows
        if row.get("FuncSys") or row.get("SfhaFunc")
    ]
    print(f"  {len(to_update)} entries have Functional System or SFHA Function set\n")

    if not to_update:
        print("Nothing to push — exiting.")
        return

    auth    = (JIRA_EMAIL, JIRA_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    ok_count = err_count = skip_count = 0

    # ── 3. Push each entry to Jira ──────────────────────────────────────────
    for row in to_update:
        key = row.get("Key", "")
        if not key or not key.startswith("MPPT-"):
            skip_count += 1
            continue

        jira_fields = {}
        if row.get("FuncSys"):
            jira_fields[FIELD_MAP["FuncSys"]]  = {"value": row["FuncSys"]}
        if row.get("SfhaFunc"):
            jira_fields[FIELD_MAP["SfhaFunc"]] = {"value": row["SfhaFunc"]}

        resp = requests.put(
            f"{JIRA_BASE}/rest/api/3/issue/{key}",
            auth=auth,
            headers=headers,
            json={"fields": jira_fields},
            timeout=30,
        )

        func_sys  = row.get("FuncSys",  "—")
        sfha_func = row.get("SfhaFunc", "—")

        if resp.ok or resp.status_code == 204:
            print(f"  ✓ {key:12s}  FuncSys={func_sys!r:25s}  SfhaFunc={sfha_func!r}")
            ok_count += 1
        else:
            print(f"  ✗ {key:12s}  HTTP {resp.status_code} — {resp.text[:200]}")
            err_count += 1

    # ── 4. Summary ──────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  Updated : {ok_count}")
    print(f"  Errors  : {err_count}")
    print(f"  Skipped : {skip_count}")
    print(f"{'─'*60}")

    if err_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
