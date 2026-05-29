"""
bulk_push_jira.py — one-time bulk push of Functional System and SFHA Function
values from the dashboard shared KV store to the corresponding Jira custom fields.

customfield_11176 = Functional System
customfield_12607 = SFHA Function

Valid Jira values for customfield_11176 (Functional System):
  Navigation, NLP, Emrys, Flight Controls, MPX Hardware Rack,
  Takeoff/Landing, CV Systems, FTS, Autochecklists, DevOps,
  FCC, ACC, Avidyne IFD, Avidyne Vantage Display, Other

Dashboard values that need manual remapping (not valid in Jira):
  "ACS"      → no automatic mapping; skipped with a warning
  "EFIS/IFD" → no automatic mapping; skipped with a warning
"""

import json, os, requests

JIRA_BASE  = os.environ["JIRA_BASE"]
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_TOKEN = os.environ["JIRA_TOKEN"]
WORKER_URL = "https://dr-sync-worker.daniela-jones.workers.dev"

FIELD_MAP = {
    "FuncSys":  "customfield_11176",   # Functional System
    "SfhaFunc": "customfield_12607",   # SFHA Function
}

# Jira allowed values for Functional System (customfield_11176)
FUNC_SYS_VALID = {
    "Navigation", "NLP", "Emrys", "Flight Controls", "MPX Hardware Rack",
    "Takeoff/Landing", "CV Systems", "FTS", "Autochecklists", "DevOps",
    "FCC", "ACC", "Avidyne IFD", "Avidyne Vantage Display", "Other",
}


def main():
    # ── 1. Fetch all shared data from the Worker KV store ──────────────────
    print("Fetching shared data from Worker KV...")
    r = requests.get(f"{WORKER_URL}?action=getAll", timeout=30)
    r.raise_for_status()
    rows = r.json().get("rows", [])
    print(f"  {len(rows)} total KV entries")

    to_update = [row for row in rows if row.get("FuncSys") or row.get("SfhaFunc")]
    print(f"  {len(to_update)} entries have Functional System or SFHA Function set\n")

    if not to_update:
        print("Nothing to push — exiting.")
        return

    auth    = (JIRA_EMAIL, JIRA_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    ok_count = err_count = skip_count = invalid_count = 0
    invalid_values = {}

    # ── 2. Push each entry to Jira ──────────────────────────────────────────
    for row in to_update:
        key = row.get("Key", "")
        if not key or not key.startswith("MPPT-"):
            skip_count += 1
            continue

        jira_fields = {}
        func_sys  = row.get("FuncSys", "")
        sfha_func = row.get("SfhaFunc", "")

        # Validate FuncSys against Jira's allowed values
        if func_sys:
            if func_sys in FUNC_SYS_VALID:
                jira_fields[FIELD_MAP["FuncSys"]] = {"value": func_sys}
            else:
                invalid_values.setdefault(func_sys, []).append(key)
                invalid_count += 1

        if sfha_func:
            jira_fields[FIELD_MAP["SfhaFunc"]] = {"value": sfha_func}

        if not jira_fields:
            skip_count += 1
            continue

        resp = requests.put(
            f"{JIRA_BASE}/rest/api/3/issue/{key}",
            auth=auth,
            headers=headers,
            json={"fields": jira_fields},
            timeout=30,
        )

        label_fs  = func_sys  or "—"
        label_sf  = sfha_func or "—"

        if resp.ok or resp.status_code == 204:
            print(f"  ✓ {key:12s}  FuncSys={label_fs!r:25s}  SfhaFunc={label_sf!r}")
            ok_count += 1
        else:
            print(f"  ✗ {key:12s}  HTTP {resp.status_code} — {resp.text[:200]}")
            err_count += 1

    # ── 3. Summary ──────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  Updated      : {ok_count}")
    print(f"  Jira errors  : {err_count}")
    print(f"  Skipped      : {skip_count}")
    if invalid_values:
        print(f"\n  ⚠ {invalid_count} ticket(s) skipped — Functional System value not")
        print(f"    recognised by Jira. Update the dashboard dropdown to use one")
        print(f"    of the valid Jira values, then re-run this script:")
        for val, keys in sorted(invalid_values.items()):
            print(f"      {val!r:20s} → {len(keys)} tickets: {', '.join(keys[:8])}{'…' if len(keys)>8 else ''}")
        print(f"\n    Valid Jira values: {', '.join(sorted(FUNC_SYS_VALID))}")
    print(f"{'─'*60}")


if __name__ == "__main__":
    main()
