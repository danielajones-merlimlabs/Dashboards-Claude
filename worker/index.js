export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResp({ results: [{ error: "Invalid JSON body" }] }, 400);
    }

    const { issueKey, updates = {}, note = "" } = body;
    if (!issueKey) return jsonResp({ results: [{ error: "Missing issueKey" }] }, 400);

    const base = env.JIRA_BASE.replace(/\/$/, "");
    const auth = btoa(`${env.JIRA_EMAIL}:${env.JIRA_TOKEN}`);
    const hdrs = {
      Authorization: `Basic ${auth}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    };

    const results = [];

    // Build Jira field payload
    const fields = {};
    if (updates.drType)  fields.customfield_11935 = { value: updates.drType };
    if (updates.system)  fields.customfield_12068 = { value: updates.system };
    if (updates.priority) fields.priority = { name: updates.priority };

    if (updates.assignee) {
      const userRes = await fetch(
        `${base}/rest/api/3/user/search?query=${encodeURIComponent(updates.assignee)}&maxResults=5`,
        { headers: hdrs }
      );
      if (userRes.ok) {
        const users = await userRes.json();
        // Match by displayName (case-insensitive)
        const match = users.find(
          (u) => u.displayName?.toLowerCase() === updates.assignee.toLowerCase()
        ) || users[0];
        if (match) {
          fields.assignee = { accountId: match.accountId };
        } else {
          results.push({ error: `Assignee not found: ${updates.assignee}` });
        }
      } else {
        results.push({ error: `User lookup failed (${userRes.status})` });
      }
    }

    // Update issue fields
    if (Object.keys(fields).length > 0) {
      const r = await fetch(`${base}/rest/api/3/issue/${issueKey}`, {
        method: "PUT",
        headers: hdrs,
        body: JSON.stringify({ fields }),
      });
      if (r.ok || r.status === 204) {
        results.push({ ok: true, action: "fields_updated" });
      } else {
        const text = await r.text();
        results.push({ error: `Field update failed (${r.status}): ${text.slice(0, 300)}` });
      }
    }

    // Add comment (posted as Jira ADF)
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
      } else {
        const text = await r.text();
        results.push({ error: `Comment failed (${r.status}): ${text.slice(0, 300)}` });
      }
    }

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
