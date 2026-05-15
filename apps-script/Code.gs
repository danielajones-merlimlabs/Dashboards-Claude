// Progress Metrics API
// Deploy as: Web App → Execute as Me → Anyone (within Merlin Labs)

const SPREADSHEET_ID = '1XQc-Mbtl-pftiQhlw67Zr8qkmNsKPmh-BUljrd_94co';
const SHEET_GID      = 1028970667;
const TARGET_CAPS    = ['LPV', 'TO', 'TD', 'ACS'];

function doGet(e) {
  try {
    const data = getProgressData();
    return respond(data);
  } catch (err) {
    return respond({ error: err.toString() });
  }
}

function getProgressData() {
  const ss    = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheets().find(s => s.getSheetId() === SHEET_GID);
  if (!sheet) throw new Error('Progress Metrics sheet not found (GID ' + SHEET_GID + ')');

  const rows = sheet.getDataRange().getValues();

  // ── Find the header row ────────────────────────────────────────────────
  let headerIdx = -1;
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].includes('Capability') && rows[i].includes('Total Points')) {
      headerIdx = i;
      break;
    }
  }
  if (headerIdx === -1) throw new Error('Could not find header row');

  const headers = rows[headerIdx];
  const col = name => headers.findIndex(h => String(h).trim() === name);

  const C = {
    cap:       col('Capability'),
    total:     col('Total Points'),
    flown:     col('Points Flown'),
    accepted:  col('Points Accepted'),
    notNeeded: col('Points Not Needed'),
    reflies:   col('Reflies To Be Flown'),
    pending:   col('Pending Review'),
    blocked:   col('Blocked Test Points'),
    leftToFly: col('Points Left to Fly'),
    pct:       col('Percent Completed'),
  };

  // ── Read capability rows ───────────────────────────────────────────────
  const capabilities = [];
  for (let i = headerIdx + 1; i < rows.length; i++) {
    const row = rows[i];
    const capName = String(row[C.cap] || '').trim();
    if (!TARGET_CAPS.includes(capName)) continue;

    const pctRaw = row[C.pct];
    // Sheets stores % cells as decimals (0.4409 = 44.09%)
    const pct = typeof pctRaw === 'number'
      ? (pctRaw <= 1 ? pctRaw * 100 : pctRaw)
      : parseFloat(String(pctRaw).replace('%','')) || 0;

    capabilities.push({
      name:       capName,
      total:      num(row[C.total]),
      flown:      num(row[C.flown]),
      accepted:   num(row[C.accepted]),
      notNeeded:  num(row[C.notNeeded]),
      reflies:    num(row[C.reflies]),
      pending:    num(row[C.pending]),
      blocked:    num(row[C.blocked]),
      leftToFly:  num(row[C.leftToFly]),
      pct:        Math.round(pct * 100) / 100,
    });

    if (capabilities.length === TARGET_CAPS.length) break;
  }

  if (capabilities.length === 0) throw new Error('No capability rows found');

  // ── Build totals ───────────────────────────────────────────────────────
  const sum = key => capabilities.reduce((s, c) => s + (c[key] || 0), 0);
  const totalPts      = sum('total');
  const totalNotNeeded= sum('notNeeded');
  const totalAccepted = sum('accepted');
  const total = {
    name:       'Total (LPV, TO, TD, ACS)',
    total:      totalPts,
    flown:      sum('flown'),
    accepted:   totalAccepted,
    notNeeded:  totalNotNeeded,
    reflies:    sum('reflies'),
    pending:    sum('pending'),
    blocked:    sum('blocked'),
    leftToFly:  sum('leftToFly'),
    pct:        totalPts - totalNotNeeded > 0
                  ? Math.round(totalAccepted / (totalPts - totalNotNeeded) * 10000) / 100
                  : 0,
  };

  return {
    lastUpdated:  new Date().toISOString(),
    capabilities,
    total,
  };
}

function num(v) {
  const n = parseFloat(v);
  return isNaN(n) ? 0 : n;
}

function respond(data) {
  const output = ContentService.createTextOutput(JSON.stringify(data));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}
