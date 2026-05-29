const CHANGELOG_KEY = "__changelog__";
const CHANGELOG_MAX = 2000;

const FIELD_LABELS = {
  FuncSys: "Functional System", SfhaFunc: "SFHA Function", DRDisposition: "DR Disposition",
  ProgApplic: "Additional Program Applicability", Campaign: "FT Campaign Blocking",
  WhereObserved: "Where Observed", ObservedBehavior: "Observed Behavior",
  ExpectedBehavior: "Expected Behavior", EffectCrew: "Effect on Crew",
  EffectOccupants: "Effect on Occupants", EffectAircraft: "Effect on Aircraft",
  ReqAffected: "Requirement Affected", FccBuildFound: "FCC Build Found",
  AccBuildFound: "ACC Build Found", AvidineBuildFound: "Avidyne Build Found",
  FccBuildFix: "FCC Fix Build", AccBuildFix: "ACC Fix Build",
  AvidineBuildFix: "Avidyne Fix Build", AvidyneFixVsChange: "Avidyne Fix vs Change",
  AvidineCR: "Avidyne CR", C130OPRs: "C130 OPRs Applicability",
  PlannedCompletion: "Planned Completion",
  Notes: "Notes", Avidyne: "Avidyne",
  "jira:drType": "DR Type (Jira)", "jira:status": "Status (Jira)",
  "jira:assignee": "Assignee (Jira)", "jira:system": "System (Jira)",
  "jira:comment": "Comment Added",
  "jira:FuncSys": "Functional System → Jira", "jira:SfhaFunc": "SFHA Function → Jira",
  "jira:funcSys": "Functional System (Jira)", "jira:sfhaFunc": "SFHA Function (Jira)",
  "jira:issueFoundOn": "Issue Found On (Jira)",
};

async function appendChangelog(env, entries) {
  const log = (await env.SHARED_NOTES.get(CHANGELOG_KEY, { type: "json" })) || [];
  for (const e of entries) log.unshift(e);
  if (log.length > CHANGELOG_MAX) log.splice(CHANGELOG_MAX);
  await env.SHARED_NOTES.put(CHANGELOG_KEY, JSON.stringify(log));
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    const url = new URL(request.url);
    const action = url.searchParams.get("action");

    // ── GET ?action=getAll — load all shared notes from KV ──
    if (request.method === "GET" && action === "getAll") {
      const list = await env.SHARED_NOTES.list();
      const rows = await Promise.all(
        list.keys
          .filter(({ name }) => name !== CHANGELOG_KEY)
          .map(async ({ name }) => {
            const val = await env.SHARED_NOTES.get(name, { type: "json" });
            return val ? { Key: name, ...val } : null;
          })
      );
      return jsonResp({ rows: rows.filter(Boolean) });
    }

    // ── GET ?action=getChangelog — return full changelog ──
    if (request.method === "GET" && action === "getChangelog") {
      const log = (await env.SHARED_NOTES.get(CHANGELOG_KEY, { type: "json" })) || [];
      return jsonResp({ log });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResp({ error: "Invalid JSON body" }, 400);
    }

    // ── POST {action:"save"} — save shared note to KV ──
    if (body.action === "save") {
      const { key, fields, user } = body;
      if (!key) return jsonResp({ error: "Missing key" }, 400);

      const existing = (await env.SHARED_NOTES.get(key, { type: "json" })) || {};
      const updated = {
        ...existing,
        ...fields,
        LastEditedBy: user || existing.LastEditedBy || "",
        LastEditedAt: new Date().toISOString(),
      };
      await env.SHARED_NOTES.put(key, JSON.stringify(updated));

      // Compute diffs and append to changelog
      const ts = updated.LastEditedAt;
      const changed = [];
      for (const [f, newV] of Object.entries(fields)) {
        const oldV = existing[f] !== undefined ? String(existing[f]) : "";
        const nV   = newV   !== undefined && newV !== null ? String(newV) : "";
        if (oldV !== nV) {
          changed.push({
            ts,
            drKey: key,
            field: FIELD_LABELS[f] || f,
            oldVal: oldV,
            newVal: nV,
            user: user || "",
          });
        }
      }
      if (changed.length > 0) await appendChangelog(env, changed);

      // ── Push FuncSys / SfhaFunc changes to Jira fields ──
      // customfield_11176 = Functional System, customfield_12607 = SFHA Function
      const JIRA_FIELD_MAP = { FuncSys: "customfield_11176", SfhaFunc: "customfield_12607" };
      const jiraFields = {};
      for (const [sfield, cfId] of Object.entries(JIRA_FIELD_MAP)) {
        if (sfield in fields && fields[sfield] !== (existing[sfield] || "")) {
          // non-empty → set value; empty string → send null to clear the field
          jiraFields[cfId] = fields[sfield] ? { value: fields[sfield] } : null;
        }
      }
      if (Object.keys(jiraFields).length > 0 && env.JIRA_EMAIL && env.JIRA_TOKEN) {
        const base = env.JIRA_BASE.replace(/\/$/, "");
        const auth = btoa(`${env.JIRA_EMAIL}:${env.JIRA_TOKEN}`);
        const jiraRes = await fetch(`${base}/rest/api/3/issue/${key}`, {
          method: "PUT",
          headers: {
            Authorization: `Basic ${auth}`,
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify({ fields: jiraFields }),
        });
        const jiraOk = jiraRes.ok || jiraRes.status === 204;
        const jiraEntries = [];
        for (const [sfield, cfId] of Object.entries(JIRA_FIELD_MAP)) {
          if (cfId in jiraFields) {
            jiraEntries.push({
              ts, drKey: key,
              field: FIELD_LABELS[`jira:${sfield}`] || `Jira: ${FIELD_LABELS[sfield] || sfield}`,
              oldVal: existing[sfield] || "",
              newVal: (fields[sfield] || "") + (jiraOk ? "" : " ⚠ Jira update failed"),
              user: user || "",
            });
          }
        }
        if (jiraEntries.length > 0) await appendChangelog(env, jiraEntries);
      }

      return jsonResp({ success: true, timestamp: updated.LastEditedAt });
    }

    // ── POST {issueKey, updates, note, user} — Jira field sync ──
    const { issueKey, updates = {}, note = "", user: jiraUser = "" } = body;
    if (!issueKey) return jsonResp({ results: [{ error: "Missing issueKey" }] }, 400);

    const base = env.JIRA_BASE.replace(/\/$/, "");
    const auth = btoa(`${env.JIRA_EMAIL}:${env.JIRA_TOKEN}`);
    const hdrs = {
      Authorization: `Basic ${auth}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    };

    const results = [];
    const changelogEntries = [];
    const ts = new Date().toISOString();

    const fields = {};
    if (updates.drType)   fields.customfield_11935 = { value: updates.drType };
    if (updates.system)   fields.customfield_12068 = { value: updates.system };
    if ("funcSys"      in updates) fields.customfield_11176 = updates.funcSys      ? { value: updates.funcSys      } : null;
    if ("sfhaFunc"     in updates) fields.customfield_12607 = updates.sfhaFunc     ? { value: updates.sfhaFunc     } : null;
    if ("issueFoundOn" in updates) fields.customfield_12605 = updates.issueFoundOn ? { value: updates.issueFoundOn } : null;

    if (updates.assignee) {
      const userRes = await fetch(
        `${base}/rest/api/3/user/search?query=${encodeURIComponent(updates.assignee)}&maxResults=5`,
        { headers: hdrs }
      );
      if (userRes.ok) {
        const users = await userRes.json();
        const match =
          users.find((u) => u.displayName?.toLowerCase() === updates.assignee.toLowerCase()) ||
          users[0];
        if (match) {
          fields.assignee = { accountId: match.accountId };
        } else {
          results.push({ error: `Assignee not found: ${updates.assignee}` });
        }
      } else {
        results.push({ error: `User lookup failed (${userRes.status})` });
      }
    }

    if (Object.keys(fields).length > 0) {
      const r = await fetch(`${base}/rest/api/3/issue/${issueKey}`, {
        method: "PUT",
        headers: hdrs,
        body: JSON.stringify({ fields }),
      });
      if (r.ok || r.status === 204) {
        results.push({ ok: true, action: "fields_updated" });
        // Log each updated Jira field
        for (const [k, v] of Object.entries(updates)) {
          changelogEntries.push({
            ts, drKey: issueKey,
            field: FIELD_LABELS[`jira:${k}`] || `Jira: ${k}`,
            oldVal: "", newVal: String(v), user: jiraUser,
          });
        }
      } else {
        const text = await r.text();
        results.push({ error: `Field update failed (${r.status}): ${text.slice(0, 300)}` });
      }
    }

    if (updates.status) {
      const transRes = await fetch(`${base}/rest/api/3/issue/${issueKey}/transitions`, { headers: hdrs });
      if (transRes.ok) {
        const { transitions = [] } = await transRes.json();
        const match = transitions.find(t => t.name.toLowerCase() === updates.status.toLowerCase() || t.to?.name?.toLowerCase() === updates.status.toLowerCase());
        if (match) {
          const tr = await fetch(`${base}/rest/api/3/issue/${issueKey}/transitions`, {
            method: "POST", headers: hdrs,
            body: JSON.stringify({ transition: { id: match.id } }),
          });
          if (tr.ok || tr.status === 204) {
            results.push({ ok: true, action: "status_transitioned" });
            changelogEntries.push({ ts, drKey: issueKey, field: "Status (Jira)", oldVal: "", newVal: updates.status, user: jiraUser });
          } else {
            const text = await tr.text();
            results.push({ error: `Status transition failed (${tr.status}): ${text.slice(0, 300)}` });
          }
        } else {
          results.push({ error: `No transition found for status: ${updates.status}` });
        }
      } else {
        results.push({ error: `Could not fetch transitions (${transRes.status})` });
      }
    }

    if (note.trim()) {
      const r = await fetch(`${base}/rest/api/3/issue/${issueKey}/comment`, {
        method: "POST",
        headers: hdrs,
        body: JSON.stringify({
          body: {
            type: "doc",
            version: 1,
            content: [{ type: "paragraph", content: [{ type: "text", text: note.trim() }] }],
          },
        }),
      });
      if (r.ok) {
        results.push({ ok: true, action: "comment_added" });
        changelogEntries.push({
          ts, drKey: issueKey,
          field: "Comment Added",
          oldVal: "", newVal: note.trim().slice(0, 120) + (note.trim().length > 120 ? "…" : ""),
          user: jiraUser,
        });
      } else {
        const text = await r.text();
        results.push({ error: `Comment failed (${r.status}): ${text.slice(0, 300)}` });
      }
    }

    if (changelogEntries.length > 0) await appendChangelog(env, changelogEntries);
    if (results.length === 0) results.push({ ok: true, action: "no_changes" });
    return jsonResp({ results });
  },
};

function jsonResp(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
