/* Outreach Studio - vanilla JS, no build step. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { leads: [], selected: new Set(), current: null, runId: null, es: null, settings: {} };
const STATUS_LABEL = {
  pending: "queued", crawling: "crawling", crawled: "crawled", composing: "writing",
  ready: "ready", sent: "sent", failed: "failed",
};

/* ------------------------------------------------------------------ utils */
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const ctype = r.headers.get("content-type") || "";
  const body = ctype.includes("json") ? await r.json().catch(() => null) : await r.text();
  if (!r.ok) throw new Error((body && body.detail) || (typeof body === "string" ? body.slice(0, 200) : "request failed"));
  return body;
}
let toastTimer = null;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), isErr ? 7000 : 3800);
}
function timeAgo(iso) {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

/* ------------------------------------------------------------------ render */
function renderTable() {
  const tb = $("#leadRows");
  if (!state.leads.length) {
    tb.innerHTML = `<tr class="empty"><td colspan="5">No leads yet. Upload a list below.</td></tr>`;
    updateCounts();
    return;
  }
  const filter = $("#filterShow")?.value || "all";
  const query = ($("#leadSearch")?.value || "").trim().toLowerCase();
  const visible = state.leads.filter((l) => {
    if (filter !== "all" && l.status !== filter) return false;
    return !query || [l.store_name, l.domain, l.email].some((value) => String(value || "").toLowerCase().includes(query));
  });
  tb.innerHTML = visible.length ? visible.map((l) => {
    const sel = state.selected.has(l.id);
    const st = l.status || "pending";
    return `<tr data-id="${l.id}" class="${sel ? "selected" : ""} ${state.current === l.id ? "current" : ""}">
      <td class="c-chk"><input type="checkbox" class="rowchk" data-id="${l.id}" ${sel ? "checked" : ""}></td>
      <td class="store-cell">${esc(l.store_name || "—")}</td>
      <td class="domain-cell" title="${esc(l.domain)}">${esc(l.domain || "—")}</td>
      <td class="email-cell" title="${esc(l.email)}">${esc(l.email || "—")}</td>
      <td><span class="pill st-${st}">${STATUS_LABEL[st] || st}</span></td>
    </tr>`;
  }).join("") : `<tr class="empty"><td colspan="5">No leads match this view.</td></tr>`;

  $$("#leadRows .rowchk").forEach((c) =>
    c.addEventListener("change", () => {
      const id = +c.dataset.id;
      c.checked ? state.selected.add(id) : state.selected.delete(id);
      renderTable();
    })
  );
  $$("#leadRows tr[data-id]").forEach((row) => row.addEventListener("click", (event) => {
    if (event.target.closest("input")) return;
    openDrawer(+row.dataset.id);
  }));
  $("#selCount").textContent = `${state.selected.size} selected`;
  updateCounts();
}

function updateCounts() {
  $("#countAll").textContent = state.leads.length;
  $("#countReady").textContent = state.leads.filter((l) => l.status === "ready").length;
  $("#countSent").textContent = state.leads.filter((l) => l.status === "sent").length;
  $("#countFailed").textContent = state.leads.filter((l) => l.status === "failed").length;
}

async function refresh() {
  const { leads } = await api("/api/leads");
  state.leads = leads;
  const ids = new Set(leads.map((l) => l.id));
  state.selected = new Set([...state.selected].filter((i) => ids.has(i)));
  if (!state.current && leads.length) {
    const initial = leads.find((lead) => lead.status === "ready") || leads[0];
    state.current = initial.id;
    await loadDrawer(initial.id);
  }
  renderTable();
}

/* -------------------------------------------------------------- upload */
async function uploadFiles(files) {
  const fd = new FormData();
  Array.from(files).forEach((f) => fd.append("files", f));
  const res = await api("/api/upload", { method: "POST", body: fd });
  showReport(res);
  await refresh();
}

function showReport(res) {
  const el = $("#uploadReport");
  const lines = [];
  for (const r of res.reports || []) {
    if (r.error) lines.push(`<div class="rline rfail"><b>${esc(r.file)}</b> ${esc(r.error)}</div>`);
    else lines.push(`<div class="rline"><b>${esc(r.file)}</b> ${r.added} row${r.added === 1 ? "" : "s"} read</div>`);
  }
  lines.push(`<div class="rline"><b>${res.added}</b> ${esc(res.message || "new rows added (duplicates skipped)")}</div>`);
  el.innerHTML = lines.join("");
  if (res.added) toast(`${res.added} row${res.added === 1 ? "" : "s"} added`);
}

/* -------------------------------------------------------------- crawl run */
async function startRun(payload) {
  try {
    const snap = await api("/api/crawl", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    state.runId = snap.run_id;
    $("#btnCancel").classList.remove("hidden");
    $("#btnCrawl").disabled = true;
    $("#progressWrap").classList.remove("hidden");
    setProgress(snap);
    listen(snap.run_id);
  } catch (e) {
    toast(e.message, true);
  }
}

function setProgress(s) {
  const pct = s.total ? Math.round((100 * (s.processed || 0)) / s.total) : 0;
  $("#progressBar").style.width = pct + "%";
  $("#progressMeta").innerHTML =
    `<span>${s.processed || 0}/${s.total || 0} stores</span><span>${s.ready || 0} ready</span>` +
    `<span>${s.failed || 0} failed</span><span>${s.elapsed || 0}s</span>`;
}

function listen(runId) {
  if (state.es) state.es.close();
  const es = new EventSource(`/api/events/${runId}`);
  state.es = es;
  es.onmessage = (ev) => {
    let d;
    try { d = JSON.parse(ev.data); } catch { return; }
    if (d.type === "progress") { setProgress(d); return; }
    if (d.type === "done") {
      es.close(); state.es = null;
      $("#btnCancel").classList.add("hidden");
      $("#btnCrawl").disabled = false;
      toast(`Finished — ${d.ready || 0} ready, ${d.failed || 0} failed`);
      refresh();
      return;
    }
    if (d.type === "update" || d.type === "stage") {
      const lead = state.leads.find((l) => l.id === d.id);
      if (lead) {
        Object.assign(lead, d);
        if (d.subjects) lead.subjects = d.subjects;
        if (d.body) lead.body_len = d.body.length;
        if (d.status === "ready" || d.status === "crawled") lead.has_facts = true;
        renderTable();
      }
      if (d.warning) toast(d.warning, true);
      if (state.current === d.id && (d.status === "ready" || d.status === "crawled")) loadDrawer(d.id);
    }
  };
  es.onerror = () => { es.close(); state.es = null; };
}

/* -------------------------------------------------------------- drawer */
async function openDrawer(id) {
  state.current = id;
  renderTable();
  await loadDrawer(id);
}

async function loadDrawer(id) {
  const l = await api(`/api/leads/${id}`);
  state.current = id;
  state.detail = l;
  $("#dStore").textContent = l.store_name || l.domain || `Row ${l.id}`;
  $("#dEmail").textContent = l.email || "no email address yet";
  $("#draftStatus").textContent = STATUS_LABEL[l.status] || l.status || "review";
  $("#draftStatus").className = `status-chip status-${l.status || "pending"}`;
  const notice = $("#draftNotice");
  if (l.error) {
    notice.textContent = `Crawl issue: ${l.error}`;
    notice.className = "draft-notice notice-error";
  } else if (l.engine && /local|template/i.test(l.engine)) {
    notice.textContent = `Draft composed locally${l.engine ? ` with ${l.engine}` : ""}. Review the store details before sending.`;
    notice.className = "draft-notice notice-warn";
  } else {
    notice.textContent = "";
    notice.className = "draft-notice hidden";
  }
  $("#dSubject").value = l.subject || "";
  $("#dBody").value = l.body || "";
  $("#dCount").textContent = l.body ? `${(l.body.match(/\S+/g) || []).length} words · ${l.body.length} chars` : "";
  $("#dEngine").textContent = l.engine ? `written by ${l.engine}` : "";
  $("#dFlags").textContent = (l.flags || []).length ? "Notes: " + l.flags.join(" · ") : "";
  $("#dShot").textContent = l.notes ? `Hook used: ${l.notes}` : "";

  // Facts tab
  const f = l.facts && typeof l.facts === "object" ? l.facts : {};
  const rows = [];
  const add = (k, v) => { if (v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && !v.length)) rows.push([k, v]); };
  add("Store name", f.store_name);
  add("Platform", f.platform === "shopify" ? "Shopify" : f.platform);
  add("Their tagline", f.tagline);
  add("Location", f.location);
  add("Founded", f.founded_year);
  add("Founder", f.founder_name);
  add("Price range", f.price_range);
  add("Categories", (f.product_types || []).join(", "));
  add("Collections", (f.collections || []).join(", "));
  add("Signals", (f.signals || []).map((s) => `<span class="tag">${esc(s)}</span>`).join(""));
  add("Shipping / returns", (f.shipping_facts || []).join(" · "));
  add("Socials", Object.entries(f.socials || {}).map(([k, v]) => `<a href="https://${k === "x" ? "x" : k}.com/${esc(v)}" target="_blank" rel="noopener">@${esc(v)}</a>`).join(", "));
  if ((f.products || []).length) {
    rows.push(["Products", (f.products || []).map((p) =>
      `<div class="prod"><b>${esc(p.title)}</b><span>${esc([p.type, p.price].filter(Boolean).join(" · "))}</span></div>`).join("")]);
  }
  if (f.about_snippet) rows.push(["About excerpt", esc(f.about_snippet.slice(0, 420)) + "…"]);
  $("#dFacts").innerHTML = rows.length
    ? rows.map(([k, v]) => `<div class="frow"><div class="fk">${esc(k)}</div><div class="fv">${v}</div></div>`).join("")
    : `<p class="hint">Nothing crawled yet. Hit “Re-crawl site”.</p>`;

  // Sources tab
  const pages = f.pages_crawled || [];
  $("#dPages").innerHTML = pages.length
    ? pages.map((p) => `<li><span class="st ${p.status === 200 ? "" : "bad"}">${p.status || "—"}</span>
        <span class="lbl">${esc(p.label)}</span>
        <a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url.replace(/^https?:\/\//, "").slice(0, 70))}</a></li>`).join("")
    : `<li class="muted">No pages recorded yet.</li>`;
}

function closeDrawer() {
  state.current = null;
  renderTable();
}

async function markSentAndNext() {
  if (!state.current) { toast("Select a lead first.", true); return; }
  const currentIndex = state.leads.findIndex((lead) => lead.id === state.current);
  await api(`/api/leads/${state.current}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "sent", sent_at: new Date().toISOString() }),
  });
  const lead = state.leads.find((item) => item.id === state.current);
  if (lead) lead.status = "sent";
  const readyLeads = state.leads.filter((item) => item.status === "ready");
  const next = readyLeads.find((item) => state.leads.indexOf(item) > currentIndex) || readyLeads[0];
  if (next) {
    state.current = next.id;
    await loadDrawer(next.id);
  } else {
    state.current = null;
    $("#dStore").textContent = "No more ready drafts";
    $("#dEmail").textContent = "All ready leads have been reviewed";
    $("#dSubject").value = "";
    $("#dBody").value = "";
    $("#draftStatus").textContent = "Complete";
    $("#draftStatus").className = "status-chip";
  }
  renderTable();
  toast("Marked as sent");
}

async function saveDraft(silent = false) {
  if (!state.current) return;
  const patch = { subject: $("#dSubject").value, body: $("#dBody").value };
  await api(`/api/leads/${state.current}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
  });
  const lead = state.leads.find((l) => l.id === state.current);
  if (lead) { lead.subject = patch.subject; lead.body_len = patch.body.length; }
  renderTable();
  if (!silent) toast("Saved");
}

/* -------------------------------------------------------------- sending */
function mailtoUrl(to, subject, body) {
  return `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}
function gmailUrl(to, subject, body) {
  return `https://mail.google.com/mail/?view=cm&fs=1&tf=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

async function sendVia(kind) {
  if (!state.current) return;
  const lead = state.detail || {};
  const to = lead.email || "";
  const subject = $("#dSubject").value.trim();
  const body = $("#dBody").value;
  if (!to) { toast("That row has no email address.", true); return; }
  if (!subject) { toast("Give it a subject line first.", true); return; }
  await saveDraft(true);
  const url = kind === "gmail" ? gmailUrl(to, subject, body) : mailtoUrl(to, subject, body);
  window.open(url, kind === "gmail" ? "_blank" : "_self");
  toast("Draft opened. Mark it sent after you send the message.");
}

/* -------------------------------------------------------------- settings */
async function loadSettings() {
  state.settings = await api("/api/settings");
  const s = state.settings;
  const map = {
    s_sender_name: "sender_name", s_sender_company: "sender_company", s_offer: "offer",
    s_video_line: "video_line", s_cta: "cta", s_subject_hint: "subject_hint", s_tone: "tone",
    s_optout_line: "optout_line", s_base_url: "base_url", s_model: "model",
    s_concurrency: "concurrency", s_request_delay: "request_delay", s_max_pages: "max_pages",
    s_seasonal_context: "seasonal_context", s_min_product_score: "min_product_score",
  };
  for (const [id, key] of Object.entries(map)) {
    const el = $("#" + id);
    if (el) el.value = s[key] ?? "";
  }
  for (const [id, key] of Object.entries({
    s_optout: "optout", s_use_ai: "use_ai", s_respect_robots: "respect_robots",
    s_find_missing_emails: "find_missing_emails", s_auto_compose: "auto_compose",
  })) {
    const el = $("#" + id);
    if (el) el.checked = !!s[key];
  }
  const badge = $("#keyBadge");
  if (s.has_api_key || s.key_from_env) {
    badge.textContent = `AI: ${s.model || "key set"}`;
    badge.className = "badge badge-ok";
  } else {
    badge.textContent = "AI: off (templates)";
    badge.className = "badge badge-muted";
  }
  $("#aiHint").textContent = s.key_from_env
    ? "A key is set via the OPENAI_API_KEY environment variable. Saving a key here overrides it."
    : "Without a key, messages are written from smart templates using the real facts from each store. Works fine, just less varied.";
}

async function saveSettings() {
  const patch = {
    sender_name: $("#s_sender_name").value, sender_company: $("#s_sender_company").value,
    offer: $("#s_offer").value, video_line: $("#s_video_line").value, cta: $("#s_cta").value,
    subject_hint: $("#s_subject_hint").value, tone: $("#s_tone").value, optout_line: $("#s_optout_line").value,
    base_url: $("#s_base_url").value, model: $("#s_model").value,
    concurrency: +$("#s_concurrency").value || 4, request_delay: +$("#s_request_delay").value || 0,
    max_pages: +$("#s_max_pages").value || 5,
    seasonal_context: $("#s_seasonal_context").value,
    min_product_score: Math.max(0, Math.min(10, Number($("#s_min_product_score").value) || 0)),
    optout: $("#s_optout").checked, use_ai: $("#s_use_ai").checked,
    respect_robots: $("#s_respect_robots").checked, find_missing_emails: $("#s_find_missing_emails").checked,
    auto_compose: $("#s_auto_compose").checked,
  };
  const key = $("#s_api_key").value.trim();
  if (key) patch.api_key = key;
  await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
  $("#s_api_key").value = "";
  await loadSettings();
  $("#settingsModal").classList.add("hidden");
  toast("Settings saved");
}

/* -------------------------------------------------------------- wiring */
function init() {
  const openSettings = async () => { await loadSettings(); $("#settingsModal").classList.remove("hidden"); };
  $("#btnSettings").addEventListener("click", openSettings);
  $("#btnTopSettings").addEventListener("click", openSettings);
  $$("[data-close]").forEach((b) => b.addEventListener("click", () => $("#settingsModal").classList.add("hidden")));
  $$("[data-close-drawer]").forEach((b) => b.addEventListener("click", closeDrawer));
  $("#btnSaveSettings").addEventListener("click", saveSettings);

  $("#btnTestKey").addEventListener("click", async () => {
    const el = $("#keyTest");
    el.textContent = "Testing…";
    const key = $("#s_api_key").value.trim();
    if (key) {
      await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: key }) });
      $("#s_api_key").value = "";
      await loadSettings();
    }
    const r = await api("/api/test-key", { method: "POST" });
    if (r.ok) {
      el.innerHTML = `<span style="color:var(--ok)">Works.</span> Sample response: “${esc(r.sample)}”`;
      loadSettings();
    } else {
      el.innerHTML = `<span style="color:var(--err)">Failed:</span> ${esc(r.error)}`;
    }
  });

  $("#btnForgetKey").addEventListener("click", async () => {
    await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clear_api_key: true }) });
    await loadSettings();
    toast("Stored API key deleted");
  });

  // upload
  const dz = $("#dropzone"), fi = $("#fileInput");
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", async (e) => {
    e.preventDefault(); dz.classList.remove("over");
    if (e.dataTransfer.files.length) {
      try { await uploadFiles(e.dataTransfer.files); } catch (err) { toast(err.message, true); }
    }
  });
  fi.addEventListener("change", async () => {
    if (fi.files.length) { try { await uploadFiles(fi.files); } catch (e) { toast(e.message, true); } fi.value = ""; }
  });
  $("#btnPaste").addEventListener("click", async () => {
    const text = $("#pasteInput").value.trim();
    if (!text) { toast("Nothing pasted yet.", true); return; }
    const fd = new FormData();
    fd.append("paste", text);
    const res = await api("/api/upload", { method: "POST", body: fd });
    showReport(res);
    $("#pasteInput").value = "";
    await refresh();
  });
  $("#btnSample").addEventListener("click", async () => {
    $("#pasteInput").value = [
      "hello@deathwishcoffee.com, deathwishcoffee.com, Death Wish Coffee",
      "browngirljane.com",
      "hello@allbirds.com | allbirds.com | Allbirds",
      "hi@bombas.com, bombas.com",
      "contact@gingerpeople.com, gingerpeople.com",
    ].join("\n");
    toast("Example list loaded — now hit “Add pasted rows”.");
  });
  $("#navUpload").addEventListener("click", () => { $("#panelUpload").open = true; $("#panelUpload").scrollIntoView({ behavior: "smooth", block: "nearest" }); });
  $("#navAddStores").addEventListener("click", () => { $("#panelUpload").open = true; $("#panelUpload").scrollIntoView({ behavior: "smooth", block: "nearest" }); });
  $("#btnExport").addEventListener("click", () => { window.location.href = "/api/export.csv?scope=ready"; });
  $("#btnSearch").addEventListener("click", () => { $("#leadSearch").classList.toggle("hidden"); $("#leadSearch").focus(); });
  $("#leadSearch").addEventListener("input", renderTable);
  $("#filterShow").addEventListener("change", renderTable);

  // runs
  $("#btnCrawl").addEventListener("click", () => startRun({ statuses: scopeStatuses(), redownload: $("#scopeSelect").value === "all" }));
  $("#btnCrawlSelected").addEventListener("click", () => {
    if (!state.selected.size) { toast("Tick some rows first.", true); return; }
    startRun({ ids: [...state.selected] });
  });
  $("#btnCancel").addEventListener("click", async () => {
    if (state.runId) await api(`/api/run/${state.runId}/cancel`, { method: "POST" });
    toast("Stopping after the current store…");
  });
  $("#checkAll").addEventListener("change", (e) => {
    state.selected = e.target.checked ? new Set(state.leads.map((l) => l.id)) : new Set();
    renderTable();
  });
  $("#btnClear").addEventListener("click", async () => {
    if (!confirm("Delete every row in the list? Personalized drafts go too.")) return;
    await api("/api/leads?keep=all", { method: "DELETE" });
    state.selected.clear();
    await refresh();
  });

  // drawer actions
  $("#btnSendMail").addEventListener("click", () => sendVia("mailto"));
  $("#btnSendGmail").addEventListener("click", () => sendVia("gmail"));
  $("#btnSaveDraft").addEventListener("click", () => saveDraft());
  $("#btnCopy").addEventListener("click", async () => {
    await navigator.clipboard.writeText(`Subject: ${$("#dSubject").value}\n\n${$("#dBody").value}`);
    toast("Subject and body copied");
  });
  $("#btnMarkSent").addEventListener("click", markSentAndNext);
  $("#btnRegen").addEventListener("click", async () => {
    await saveDraft(true);
    const r = await api(`/api/leads/${state.current}/compose`, { method: "POST" });
    toast("Rewriting…");
    if (r.run_id) listen(r.run_id);
  });
  $("#btnRecrawl").addEventListener("click", async () => {
    const r = await api(`/api/leads/${state.current}/recrawl`, { method: "POST" });
    toast("Re-crawling…");
    $("#progressWrap").classList.remove("hidden");
    $("#btnCancel").classList.remove("hidden");
    listen(r.run_id);
  });
  $("#dBody").addEventListener("input", () => {
    const v = $("#dBody").value;
    $("#dCount").textContent = `${(v.match(/\S+/g) || []).length} words · ${v.length} chars`;
  });

  // tabs
  $$(".tab").forEach((t) =>
    t.addEventListener("click", () => {
      $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
      $$(".tabpane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== t.dataset.tab));
    })
  );

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeDrawer(); $("#settingsModal").classList.add("hidden"); }
  });

  refresh();
  loadSettings();
}

function scopeStatuses() {
  const v = $("#scopeSelect").value;
  if (v === "failed") return ["failed"];
  if (v === "all") return null;
  return ["pending", "crawled", "failed"];
}

document.addEventListener("DOMContentLoaded", init);
