"""
bulk_push_jira.py — one-time bulk push of Functional System and SFHA Function
values from the dashboard shared KV store to the corresponding Jira custom fields.

customfield_11176 = Functional System
customfield_12607 = SFHA Function

Mapping rules:
  "ACS"      → pushed as "ACC" (ACC is the Jira field value)
  "EFIS/IFD" → skipped (no Jira equivalent)
  all others → pushed as-is
"""

import os, requests

JIRA_BASE  = os.environ["JIRA_BASE"]
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_TOKEN = os.environ["JIRA_TOKEN"]
WORKER_URL = "https://dr-sync-worker.daniela-jones.workers.dev"

FIELD_MAP = {
    "FuncSys":  "customfield_11176",   # Functional System
    "SfhaFunc": "customfield_12607",   # SFHA Function
}

# Dashboard value → Jira value (None = skip)
FUNC_SYS_REMAP = {
    "ACS":      "ACC",   # ACS in dashboard = ACC in Jira
    "EFIS/IFD": None,    # no Jira equivalent — skip
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
    ok_count = err_count = skip_count = 0

    # ── 2. Push each entry to Jira ──────────────────────────────────────────
    for row in to_update:
        key = row.get("Key", "")
        if not key or not key.startswith("MPPT-"):
            skip_count += 1
            continue

        jira_fields = {}
        func_sys  = row.get("FuncSys", "")
        sfha_func = row.get("SfhaFunc", "")

        if func_sys:
            if func_sys in FUNC_SYS_REMAP:
                mapped = FUNC_SYS_REMAP[func_sys]
                if mapped is None:
                    print(f"  – {key:12s}  FuncSys={func_sys!r} skipped (no Jira equivalent)")
                    skip_count += 1
                    continue
                jira_fields[FIELD_MAP["FuncSys"]] = {"value": mapped}
            else:
                jira_fields[FIELD_MAP["FuncSys"]] = {"value": func_sys}

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

        label_fs = FUNC_SYS_REMAP.get(func_sys, func_sys) if func_sys else "—"
        label_sf = sfha_func or "—"

        if resp.ok or resp.status_code == 204:
            print(f"  ✓ {key:12s}  FuncSys={label_fs!r:25s}  SfhaFunc={label_sf!r}")
            ok_count += 1
        else:
            print(f"  ✗ {key:12s}  HTTP {resp.status_code} — {resp.text[:200]}")
            err_count += 1

    # ── 3. Summary ──────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  Updated : {ok_count}")
    print(f"  Errors  : {err_count}")
    print(f"  Skipped : {skip_count}  (EFIS/IFD or non-MPPT keys)")
    print(f"{'─'*60}")


if __name__ == "__main__":
    main()
