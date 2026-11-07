/* Mollet front end. Talks only to Mollet's own server; the Otari key stays there. */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function usd(v, { approx = false } = {}) {
    const n = Number(v || 0);
    let s;
    if (n === 0) s = "$0";
    else if (n < 0.0001) s = "<$0.0001";
    else if (n < 0.01) s = "$" + n.toFixed(4);
    else s = "$" + n.toFixed(n < 1 ? 3 : 2);
    return (approx ? "~" : "") + s;
  }

  /* Small, safe Markdown: escape first, then a few constructs. Links must be http(s). */
  function inline(s) {
    return s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])_([^_]+)_(?=[\s).,!?]|$)/g, "$1<em>$2</em>")
      .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,!?]|$)/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/(^|\s)(https?:\/\/[^\s<]+[^\s<.,)])/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
  }
  function md(src) {
    const parts = esc(src || "").split(/```[a-zA-Z0-9_+-]*\n?/);
    let html = "";
    parts.forEach((chunk, i) => {
      if (i % 2 === 1) { html += "<pre><code>" + chunk.replace(/\n$/, "") + "</code></pre>"; return; }
      const blocks = chunk.split(/\n{2,}/);
      for (const b of blocks) {
        const lines = b.split("\n").filter((l) => l.trim() !== "");
        if (!lines.length) continue;
        if (lines.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
          html += "<ol>" + lines.map((l) => "<li>" + inline(l.replace(/^\s*\d+[.)]\s+/, "")) + "</li>").join("") + "</ol>";
        } else if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
          html += "<ul>" + lines.map((l) => "<li>" + inline(l.replace(/^\s*[-*]\s+/, "")) + "</li>").join("") + "</ul>";
        } else {
          html += "<p>" + lines.map(inline).join("<br>") + "</p>";
        }
      }
    });
    return html;
  }

  async function api(path, body) {
    const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch(path, opts);
    let data = {};
    try { data = await res.json(); } catch (_) { /* non-JSON error */ }
    return { ok: res.ok, status: res.status, data };
  }

  function notice(err, cls) {
    const o = err.otari || {};
    const meta = o.code ? `Otari ${o.status} · ${o.code}${o.scope ? " · scope " + o.scope : ""}${o.request_id ? " · " + o.request_id : ""}` : (err.app_rule ? "App rule (Mollet), not an Otari guardrail" : "");
    const kindCls = cls || ({ wallet_empty: "warn", class_budget: "warn", guardrail: "danger", error: "danger", setup: "warn" }[err.kind] || "");
    return `<div class="notice ${kindCls}" role="alert"><div class="n-body"><strong>${esc(err.title || "Something went wrong")}</strong><p>${esc(err.message || "")}</p>${meta ? `<div class="n-meta">${esc(meta)}</div>` : ""}</div></div>`;
  }

  function meterClass(pct) { return pct >= 100 ? "empty" : pct >= 80 ? "warn" : ""; }

  function traceHtml(d, label = "Otari trace") {
    if (!d || !Object.keys(d).length) return "";
    const tools = (d.tool_calls || []).map((t) => {
      let extra = "";
      if (t.type === "web_search") extra = ` "${t.query || ""}" → ${(t.sources || []).join(", ")}`;
      if (t.type === "mcp") extra = ` ${t.server || ""}.${t.name || ""}`;
      if (t.type === "code_execution") extra = ` exit ${t.exit_code ?? "?"}`;
      return `${t.type} [${t.status}]${extra}`;
    });
    const guards = (d.guardrails || []).map((g) => `${g.profile}:${g.mode}:${g.status}${g.valid === false ? ":flagged" : ""}`);
    const rows = [
      ["requested", d.model_requested],
      ["served by", d.model_served || "–"],
      ["provider", d.provider || "–"],
      ["fallback", `<span class="flag ${d.fallback ? "flag-yes" : "flag-no"}">${d.fallback ? "yes" : "no"}</span>${d.attempt_count ? " · " + d.attempt_count + " attempt(s)" : ""}`, true],
      ["cost", d.cost_usd !== undefined ? "$" + Number(d.cost_usd).toFixed(6) + " (usage.cost_usd)" : "–"],
      ["tokens", d.tokens ?? "–"],
      ["tools", tools.length ? tools.join("<br>") : "none", true],
      ["mcp", d.mcp || "–"],
      ["guardrails", guards.length ? guards.join(", ") : "org-mandated only"],
      ["answer check", d.leak_check || "–"],
      ["request id", d.request_id || "–"],
    ];
    return `<details class="trace"><summary>${esc(label)}</summary><dl class="kv">${rows.map(([k, v, raw]) => `<dt>${k}</dt><dd>${raw ? (k === "tools" ? v.split("<br>").map(esc).join("<br>") : v) : esc(v)}</dd>`).join("")}</dl></details>`;
  }

  /* ── Learn page ─────────────────────────────────────────────────────────── */
  function learn() {
    const state = JSON.parse($("#state").textContent);
    const sid = state.student.id, pid = state.problem.id;
    const code = $("#code");
    let busy = false;

    $("#statement").innerHTML = inline(esc(state.problem.statement));
    const draftKey = `mollet:draft:${sid}:${pid}`;
    let draft = null;
    try { draft = localStorage.getItem(draftKey); } catch (_) { /* storage blocked */ }
    code.value = draft ?? state.starter;
    code.addEventListener("input", () => { try { localStorage.setItem(draftKey, code.value); } catch (_) {} });
    code.addEventListener("keydown", (e) => {
      if (e.key === "Tab" && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        const { selectionStart: a, selectionEnd: b } = code;
        code.setRangeText("    ", a, b, "end");
        code.dispatchEvent(new Event("input"));
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); submit(); }
    });

    $("#student-switch").addEventListener("change", (e) => { location.href = `/learn/${e.target.value}/${pid}`; });

    function nextLevel() { return state.hints.reduce((m, h) => Math.max(m, h.level), 0) + 1; }

    function renderLadder() {
      const next = nextLevel();
      $("#ladder").innerHTML = state.ladder.map((r) => {
        const p = state.prices[r.level] || {};
        const cls = r.level < next ? "used" : r.level === next ? "next" : "";
        return `<li class="rung ${cls}"><span class="rung-n">${r.level}</span><div><div class="rung-name">${esc(r.name)}</div><div class="rung-tag">${esc(r.tagline)}</div></div><div class="rung-price">${usd(p.usd, { approx: !p.measured })}<small>${r.tier === "mentor" ? "Mentor model" : "Hinter model"}</small></div></li>`;
      }).join("");
      const btn = $("#ask");
      if (next > state.ladder.length) {
        btn.disabled = true; btn.textContent = "Top of the ladder";
      } else {
        const r = state.ladder[next - 1], p = state.prices[next] || {};
        btn.disabled = busy;
        btn.innerHTML = `Get hint ${next} · ${esc(r.name)} <span class="price">${usd(p.usd, { approx: !p.measured })}</span>`;
      }
    }

    function renderWallet(w) {
      if (!w) return;
      $("#wallet-amt").innerHTML = `${usd(w.remaining_usd)}<small>left</small>`;
      const m = $("#wallet-meter");
      m.className = "meter " + meterClass(w.pct_used);
      m.setAttribute("aria-valuenow", Math.round(w.pct_used));
      $("span", m).style.width = Math.min(100, w.pct_used) + "%";
      $("#wallet-spent").textContent = `${usd(w.spend_usd)} spent · ${w.requests || 0} requests`;
      $("#wallet-limit").textContent = `${usd(w.limit_usd)} / week`;
      $("#wallet-refill").textContent = w.pct_used >= 100 ? `Empty · refills ${w.refills}` : `Refills ${w.refills}`;
      $("#wallet-source").textContent = w.source === "otari" ? "Otari end-user budget" : w.source;
    }

    function hintHtml(h) {
      const sources = (h.sources || []).map((s) => `<a class="source" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer"><span class="tag">Docs</span>${esc(s.title || s.url)}</a>`).join("");
      return `<article class="hint" id="hint-${h.id}">
        <div class="hint-head"><span class="lvl">Hint ${h.level} · ${esc(h.name)}</span><span class="cost">${usd(h.cost_usd)}</span></div>
        ${h.question ? `<div class="hint-q">You asked: ${esc(h.question)}</div>` : ""}
        <div class="hint-body">${md(h.text)}</div>
        ${sources ? `<div class="sources">${sources}</div>` : ""}
        ${h.redacted ? `<p class="redacted-note">Mollet removed code from this hint because it gave away the answer (app rule).</p>` : ""}
        ${traceHtml(h.debug)}
      </article>`;
    }

    function renderHints() {
      const el = $("#hints");
      el.innerHTML = state.hints.length ? state.hints.slice().reverse().map(hintHtml).join("") : `<p class="empty">No hints yet. Try first, then climb the ladder one rung at a time. Cheaper rungs come first.</p>`;
    }

    function renderIndependence(ind) {
      if (!ind) return;
      $("#independence").textContent = ind.score === null || ind.score === undefined ? "–" : ind.score;
      $("#independence-sub").textContent = ind.solved ? `${ind.solved} solved` : "Solve a problem to get one";
    }

    async function refreshWallet() {
      const r = await api(`/api/wallet/${sid}`);
      if (r.ok) renderWallet(r.data);
      else $("#wallet-source").textContent = "unavailable";
    }

    $("#ask-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (busy) return;
      busy = true; renderLadder();
      const status = $("#ask-status");
      status.innerHTML = `<span class="hint-text"><span class="spinner" aria-hidden="true"></span> Asking Otari for hint ${nextLevel()}…</span>`;
      const r = await api("/api/hint", { student_id: sid, problem_id: pid, question: $("#question").value, code: code.value });
      busy = false;
      if (r.ok) {
        status.innerHTML = "";
        state.hints.push(r.data.hint);
        state.prices = r.data.prices || state.prices;
        $("#question").value = "";
        renderHints();
      } else {
        status.innerHTML = notice(r.data.error || { title: "Request failed", message: `HTTP ${r.status}` });
      }
      if (r.data && r.data.wallet) renderWallet(r.data.wallet);
      renderLadder();
    });

    async function submit() {
      const btn = $("#submit");
      if (btn.disabled) return;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner" aria-hidden="true"></span> Running in Otari sandbox…`;
      const out = $("#results");
      out.classList.add("show");
      out.innerHTML = `<div class="panel-body"><div class="skeleton" style="width:40%"></div><div class="skeleton"></div><div class="skeleton" style="width:70%"></div></div>`;
      const r = await api("/api/submit", { student_id: sid, problem_id: pid, code: code.value });
      btn.disabled = false; btn.textContent = "Run hidden tests";
      if (!r.ok) { out.innerHTML = `<div class="panel-body">${notice(r.data.error || { title: "Couldn't run the tests", message: `HTTP ${r.status}` })}</div>`; return; }
      const d = r.data;
      let body = "";
      if (d.load_error) {
        const e = d.load_error;
        body += `<div class="verdict fail"><strong>Your code didn't run</strong><span class="chip">${esc(e.type)}${e.line ? " · line " + e.line : ""}</span></div><pre class="out">${esc(e.message)}</pre>`;
      } else {
        body += `<div class="verdict ${d.passed ? "pass" : "fail"}"><strong>${d.passed ? "All tests passed" : `${d.passed_count} of ${d.total} tests passed`}</strong><span class="chip chip-primary">real sandbox output</span></div>`;
        body += `<table class="test-table"><thead><tr><th>Result</th><th>Input</th><th>Expected</th><th>Got</th></tr></thead><tbody>${d.results.map((t) => `<tr><td class="st ${t.passed ? "ok" : "bad"}">${t.passed ? "Pass" : "Fail"}</td><td>${esc(t.args)}</td><td>${esc(t.expected)}</td><td>${esc(t.error || t.got)}</td></tr>`).join("")}</tbody></table>`;
      }
      if (d.stdout && d.stdout.trim()) body += `<pre class="out" aria-label="Your print output">${esc(d.stdout)}</pre>`;
      body += `<div class="feedback"><div class="who">Grader${d.grader ? " · " + esc(d.grader.model_served || d.grader.model_requested) : " (offline: feedback from test results)"}</div>${md(d.feedback)}</div>`;
      if (d.grader_error) body += `<p class="hint-text" style="margin-top:8px">Grader model unavailable (${esc(d.grader_error)}). Verdict above is still from the sandbox.</p>`;
      const sandboxTrace = `<details class="trace"><summary>Otari trace · sandbox verdict</summary><dl class="kv"><dt>verdict</dt><dd>POST /code/execute (no model)</dd><dt>request id</dt><dd>${esc(d.sandbox_request_id || "–")}</dd></dl></details>`;
      out.innerHTML = `<div class="panel-head"><h2>Test results</h2><span class="hint-text">Hidden tests · Otari code execution</span></div><div class="panel-body">${body}</div>${sandboxTrace}${d.grader ? traceHtml(d.grader, "Otari trace · Grader model") : ""}`;
      if (d.passed) { $("#solved-chip").hidden = false; const t = document.querySelector('.rail a[aria-current="page"] .tick'); if (t) t.classList.add("done"); }
      renderIndependence(d.independence);
    }
    $("#submit").addEventListener("click", submit);

    renderLadder();
    renderHints();
    renderIndependence(state.independence);
    refreshWallet();
  }

  /* ── Teacher page ───────────────────────────────────────────────────────── */
  function teacher() {
    async function load() {
      const r = await api("/api/class");
      if (!r.ok) { $("#students").innerHTML = `<tr><td colspan="6">${notice({ title: "Couldn't load the class", message: `HTTP ${r.status}` })}</td></tr>`; return; }
      const d = r.data, cb = d.class_budget || {};
      if (cb.available && cb.limit_usd !== undefined) {
        $("#c-used").textContent = Math.round(cb.pct_used) + "%";
        $("#c-sub").textContent = `${usd(cb.used_usd)} of ${usd(cb.limit_usd)}${cb.limit_is_display ? " (display cap)" : ""} · ${cb.scope} · resets ${cb.resets}`;
        const m = $("#c-meter"); m.className = "meter " + meterClass(cb.pct_used); $("span", m).style.width = Math.min(100, cb.pct_used) + "%";
      } else if (cb.available) {
        $("#c-used").textContent = cb.remaining_usd != null ? usd(cb.remaining_usd) + " left" : "No cap";
        $("#c-sub").textContent = "Set a weekly workspace budget in the Otari dashboard";
      } else {
        $("#c-used").textContent = "–"; $("#c-sub").textContent = cb.reason || "unavailable";
      }
      const st = d.students;
      const hints = st.reduce((a, s) => a + s.hints, 0);
      $("#c-hints").textContent = hints;
      $("#c-hint-cost").textContent = usd(st.reduce((a, s) => a + s.hint_cost_usd, 0)) + " total";
      const solved = st.reduce((a, s) => a + s.solved, 0);
      $("#c-solved").textContent = solved;
      $("#c-solved-sub").textContent = `of ${st.length * d.total_problems} student-problems`;
      const scored = st.filter((s) => s.independence !== null);
      $("#c-ind").textContent = scored.length ? Math.round(scored.reduce((a, s) => a + s.independence, 0) / scored.length) : "–";

      $("#students").innerHTML = st.map((s) => {
        const w = s.wallet;
        return `<tr><td><strong>${esc(s.name)}</strong><div class="hint-text mono">${esc(s.id)}</div></td>
          <td><span class="mini-meter ${meterClass(w.pct_used)}"><span style="width:${Math.min(100, w.pct_used)}%"></span></span>${usd(w.spend_usd)} / ${usd(w.limit_usd)}${w.pct_used >= 100 ? ` <span class="chip">empty · refills ${esc(w.refills)}</span>` : ""}</td>
          <td class="num">${s.hints}</td><td class="num">${s.solved}</td>
          <td class="num"><span class="score">${s.independence ?? "–"}</span></td>
          <td class="num"><a href="/learn/${encodeURIComponent(s.id)}">Open</a></td></tr>`;
      }).join("");

      $("#refusals").innerHTML = d.refusals.length ? d.refusals.map((x) => `<div class="list-row"><span><strong>${esc(x.kind)}</strong>${x.scope ? " · " + esc(x.scope) : ""} · ${esc(x.student_id)}</span><span class="mono">${esc(x.created_at.replace("T", " ").slice(0, 16))}</span></div>`).join("") : `<div class="list-row empty">Nothing blocked yet.</div>`;
      $("#models").innerHTML = d.models.length ? d.models.map((m) => `<div class="list-row"><span><span class="mono">${esc(m.model_requested)}</span> → <strong>${esc(m.model_served || "?")}</strong>${m.fallbacks ? ` <span class="flag flag-yes">${m.fallbacks} fallback</span>` : ""}</span><span class="mono">${m.n} · ${usd(m.cost)}</span></div>`).join("") : `<div class="list-row empty">No hints yet.</div>`;
      const byLevel = [1, 2, 3, 4, 5].map((l) => st.reduce((a, s) => a + (s.by_level[l] || 0), 0));
      const max = Math.max(1, ...byLevel);
      const names = ["Point", "Explain", "Approach", "Sketch", "Walk-through"];
      $("#rungs").innerHTML = byLevel.map((n, i) => `<div class="ladder-bar"><span>${i + 1} · ${names[i]}</span><span class="track"><span style="width:${(100 * n) / max}%"></span></span><span class="mono">${n}</span></div>`).join("");
    }
    $("#refresh").addEventListener("click", load);
    load();
  }

  /* ── Status page ────────────────────────────────────────────────────────── */
  function status() {
    const pill = (s) => `<span class="status-dot status-${s}">${{ ok: "In use", setup: "Needs setup", off: "Off" }[s]}</span>`;
    async function load() {
      const r = await api("/api/status");
      if (!r.ok) { $("#features").innerHTML = notice({ title: "Status unavailable", message: `HTTP ${r.status}` }); return; }
      const d = r.data, pr = d.probes, c = d.counters;
      const toolList = (() => {
        const t = pr.tools.ok ? pr.tools.data : null;
        const arr = Array.isArray(t) ? t : (t && (t.data || t.tools)) || [];
        return arr;
      })();
      const tool = (name) => toolList.find((t) => [t.type, t.name, t.id].includes(name));
      const avail = (name) => { const t = tool(name); return t ? (t.available !== false) : null; };
      const ce = avail("otari_code_execution"), ws = avail("otari_web_search");
      const profiles = pr.guardrail_profiles.ok ? (pr.guardrail_profiles.data.profiles || []).map((p) => p.profile) : [];
      const budgets = pr.end_user_budgets.ok ? pr.end_user_budgets.data : [];
      const kb = pr.key_budget.ok ? pr.key_budget.data : null;
      const ceilings = kb ? (kb.limits || []).filter((l) => l.scope !== "user") : [];
      const isPolicy = (m) => m && !/[:/]/.test(m);
      const f = [
        { t: "Multiple models, distinct roles", s: d.models.served.length ? "ok" : (d.configured ? "setup" : "setup"),
          p: `Hinter <span class="mono">${esc(d.models.hinter)}</span> writes rungs 1–3, Mentor <span class="mono">${esc(d.models.mentor)}</span> rungs 4–5, Grader <span class="mono">${esc(d.models.grader)}</span> reviews code. All open-weight.`,
          live: d.models.served.length ? "Served so far: " + d.models.served.map(esc).join(", ") : "No hints served yet.", w: "mollet/config.py · hints.model_for() · grader.grade()" },
        { t: "Per-user budgets (wallets)", s: budgets.length ? "ok" : "setup",
          p: "One service key; every hint sets <span class=\"mono\">user</span> to the student id, so Otari bills that student's end-user budget. The wallet bar reads <span class=\"mono\">spend</span> vs <span class=\"mono\">max_budget</span>.",
          live: budgets.length ? budgets.map((b) => `${esc(b.name || b.budget_id)}: ${usd(b.max_budget)} each · ${b.end_user_count} students`).join("; ") : (pr.end_user_budgets.error ? esc(pr.end_user_budgets.error) + " (is this a service key with end-user budgets?)" : "No end-user budget on the key"), w: "otari.chat(user=…) · wallet.wallet() · GET /end-users" },
        { t: "Budgets / spending limits", s: ceilings.length ? "ok" : "setup",
          p: "A weekly workspace budget is the teacher's cap for the whole class. Hitting it pauses hints for everyone with a clear message.",
          live: ceilings.length ? ceilings.map((l) => `${esc(l.scope)}: ${l.remaining_usd != null ? usd(l.remaining_usd) + " left" : "–"}`).join("; ") + ` · ${c.budget_blocks} refusals` : "No workspace/key ceiling found via GET /key/budget", w: "wallet.class_budget() · main.refusal()" },
        { t: "Routing and fallbacks", s: (isPolicy(d.models.hinter) || isPolicy(d.models.mentor)) ? (c.hints ? "ok" : "setup") : "setup",
          p: "Hinter is a fallback-chain policy; Mentor is a \"tier down when the budget fills up\" policy. Every hint's trace shows <span class=\"mono\">Otari-Model</span> and <span class=\"mono\">Otari-Fallback</span>.",
          live: `${c.fallbacks} fallback(s) across ${c.hints} hints`, w: "otari.chat() reads Otari-Model / Otari-Fallback / Otari-Attempt-Count" },
        { t: "Code execution", s: ce === false ? "setup" : (c.graded ? "ok" : (ce ? "ok" : "setup")),
          p: "Submissions run against hidden tests in Otari's sandbox (<span class=\"mono\">POST /code/execute</span>), and the Grader may run its own checks with <span class=\"mono\">otari_code_execution</span>. Hints whose code passes the tests are rejected.",
          live: (ce === null ? "Tool listing unavailable" : ce ? "Available in workspace" : "Not available: enable Tools → Code execution") + ` · ${c.graded} submissions graded`, w: "grader.run_tests() · grader.grade() · hints.runs_as_solution()" },
        { t: "Guardrails", s: (d.guardrail_profiles.length || c.guardrail_blocks) ? "ok" : "setup",
          p: "Organization guardrails in block mode stop personal info (phone numbers, addresses) and unsafe content before any model sees it. \"Never the full answer\" is Mollet's own app rule, not an Otari guardrail.",
          live: `Request profiles: ${d.guardrail_profiles.length ? d.guardrail_profiles.map(esc).join(", ") : "none (org-mandated only)"} · available: ${profiles.length ? profiles.map(esc).join(", ") : "–"} · ${c.guardrail_blocks} blocked${d.app_pii_precheck ? " · app PII pre-check ON" : ""}`, w: "hints.request_hint(guardrails=…) · main.refusal()" },
        { t: "Web search", s: ws === false ? "setup" : (c.search_hints ? "ok" : (ws ? "ok" : "setup")),
          p: "Rung 1 (\"Point\") searches once (<span class=\"mono\">max_uses: 1</span>) for one official docs page and shows it as a link card.",
          live: (ws === null ? "Tool listing unavailable" : ws ? "Available in workspace" : "Not available in workspace") + ` · ${c.search_hints} hints used search`, w: "hints.request_hint() level 1 · otari_tool_calls[type=web_search]" },
        { t: "MCP", s: d.mcp_server_id ? (c.mcp_calls ? "ok" : "setup") : "off",
          p: "Mollet's own classroom MCP server (<span class=\"mono\">/classroom/mcp</span>) exposes <span class=\"mono\">get_problem</span> and <span class=\"mono\">get_student_history</span>, so hints can recall past mistakes.",
          live: d.mcp_server_id ? `Server id ${esc(d.mcp_server_id)} · ${c.mcp_calls} hints called it` : "Set MOLLET_MCP_SERVER_ID after registering the public URL in Tools → MCP servers", w: "mollet/mcp_server.py · mcp_server_ids in hints.request_hint()" },
      ];
      $("#features").innerHTML = f.map((x, i) => `<section class="feature"><div class="feature-head"><h2><span class="idx">0${i + 1}</span>${x.t}</h2>${pill(x.s)}</div><p>${x.p}</p><div class="live">${x.live}</div><div class="where">${esc(x.w)}</div></section>`).join("");
    }
    $("#refresh").addEventListener("click", load);
    load();
  }

  window.Mollet = { learn, teacher, status, md };
})();
