# FFT + MPPT DR Tracker

Interactive DR dashboard, auto-synced from Jira daily at 6am ET via GitHub Actions.

## How it works

| File | Purpose |
|---|---|
| `template.html` | Page layout, filters, JS — never auto-modified |
| `index.html` | Built file served by GitHub Pages — rebuilt on every sync |
| `scripts/sync.py` | Fetches Jira, injects data into template → index.html |
| `.github/workflows/sync.yml` | Runs sync.py daily at 6am ET (11:00 UTC) |

## Setup (one-time)

### 1. Add GitHub Secrets
Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret name | Value |
|---|---|
| `JIRA_EMAIL` | Your Atlassian account email (e.g. `you@merlinlabs.com`) |
| `JIRA_TOKEN` | Your Jira API token — generate at https://id.atlassian.com/manage-profile/security/api-tokens |

### 2. Enable GitHub Pages
Go to **Settings → Pages** and set:
- Source: **Deploy from a branch**
- Branch: `main` / `(root)`

Your dashboard will be live at `https://YOUR-USERNAME.github.io/YOUR-REPO-NAME/`

### 3. Run manually anytime
Go to **Actions → Daily DR Sync → Run workflow** to trigger a sync outside the schedule.

## What syncs daily
- **All MPPT DRs** (any status except Done/Closed/Won't Fix/Duplicate)
- **FFT DRs for N208B and ZK-MLN only**
- Updates: Status, Assignee, DR Type, Priority, Labels, Linked Issues, Comments, Updated date
- New DRs are automatically added
- Tickets that move to Done/Closed appear highlighted in red as `[CLOSED]`

## User data (Notes + Avidyne checkboxes)
Notes and Avidyne checkbox overrides are saved in **browser localStorage** — they survive syncs since the script only replaces the data block, not the page structure. Use **Export Notes CSV** to back them up.
