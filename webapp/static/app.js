// ─── helpers ──────────────────────────────────────────────
async function api(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = {};
    try { detail = (await resp.json()).detail || {}; } catch (e) { /* ignore */ }
    const err = new Error(detail.error || resp.statusText || "request failed");
    err.status = resp.status;
    err.detail = detail;
    throw err;
  }
  return resp.json();
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(s + (s.length === 10 ? "T00:00:00" : ""));
  if (isNaN(d)) return s;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

// ─── run controls + SSE log ──────────────────────────────
const drawer = () => document.getElementById("log-drawer");
const logBody = () => document.getElementById("log-body");

function openLog(title) {
  document.getElementById("log-title").textContent = title;
  logBody().textContent = "";
  drawer().classList.remove("hidden");
  drawer().classList.remove("failed");
}

function appendLogLine(text) {
  const body = logBody();
  body.textContent += text + "\n";
  body.scrollTop = body.scrollHeight;
}

let activeSource = null;

function connectStream(runId, label) {
  if (activeSource) activeSource.close();
  openLog(label + " · " + runId);
  const es = new EventSource(`/api/runs/${runId}/stream`);
  activeSource = es;
  es.addEventListener("line", (ev) => appendLogLine(JSON.parse(ev.data)));
  es.addEventListener("done", (ev) => {
    const data = JSON.parse(ev.data);
    es.close();
    activeSource = null;
    if (data.status === "failed") {
      drawer().classList.add("failed");
      appendLogLine(`\n[run failed, exit ${data.returncode}]`);
    }
    refreshStatus();
    refreshPage();
  });
  es.onerror = () => { /* EventSource auto-reconnects; replay is idempotent */ };
}

async function startRun(kind) {
  setRunButtonsDisabled(true);
  try {
    const run = kind === "enrich"
      ? await api("/api/enrich", { method: "POST" })
      : await api("/api/scrape", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hours: kind === "24h" ? 24 : 168 }),
        });
    connectStream(run.id, run.label);
    refreshStatus();
  } catch (err) {
    if (err.status === 409) alert("A run is already active — wait for it to finish.");
    else alert("Failed to start run: " + err.message);
  } finally {
    setRunButtonsDisabled(false);
  }
}

function setRunButtonsDisabled(disabled) {
  document.querySelectorAll(".run-controls .btn").forEach((b) => (b.disabled = disabled));
}

async function refreshStatus() {
  const pill = document.getElementById("status-pill");
  try {
    const s = await api("/api/status");
    const banner = document.getElementById("catalog-banner");
    banner.classList.toggle("hidden", s.has_catalog !== false);
    if (s.current_run) {
      pill.textContent = s.current_run.label + "…";
      pill.className = "pill running";
      if (!activeSource) connectStream(s.current_run.id, s.current_run.label);
    } else if (s.last_run) {
      pill.textContent = s.last_run.status === "done" ? "last run ok" : "last run failed";
      pill.className = "pill " + (s.last_run.status === "done" ? "ok" : "failed");
      pill.title = "catalog updated " + (s.catalog_mtime || "?");
    } else {
      pill.textContent = s.has_catalog ? "catalog ready" : "no catalog";
      pill.className = "pill " + (s.has_catalog ? "ok" : "failed");
    }
  } catch (e) {
    pill.textContent = "server error";
    pill.className = "pill failed";
  }
}

// ─── dashboard ────────────────────────────────────────────
async function loadDashboard() {
  try {
    const [summary, cfg] = await Promise.all([api("/api/summary"), api("/api/config")]);
    document.getElementById("stat-new").textContent = summary.new_jobs;
    document.getElementById("stat-total").textContent = summary.total_jobs;
    const sites = Object.entries(summary.by_site)
      .map(([s, n]) => `${s} ${n}`).join(" · ");
    document.getElementById("stat-sites").textContent = sites || "—";
    document.getElementById("stat-file").textContent = summary.last_output_file || "—";
    document.getElementById("stat-file").style.fontSize = "13px";
    document.getElementById("config-line").textContent =
      `Searching ${cfg.titles.length} titles × ${cfg.locations.length} locations × ` +
      `${cfg.sites.length} sites, ${cfg.results_per_search} results per search.`;
    const comps = document.getElementById("top-companies");
    comps.innerHTML = "";
    summary.top_companies.forEach((c) => {
      const row = el("div", "row");
      row.appendChild(el("span", "row-title", c.company));
      row.appendChild(el("span", "badge", c.total + " jobs"));
      if (c.recent) row.appendChild(el("span", "chip", c.recent + " last 7d"));
      if (c.new) row.appendChild(el("span", "chip new", c.new + " new"));
      row.addEventListener("click", () => (location.href = `/jobs?company=${encodeURIComponent(c.company)}`));
      comps.appendChild(row);
    });
    const techs = document.getElementById("top-techs");
    techs.innerHTML = "";
    summary.top_techs.forEach((t) => {
      const chip = el("a", "chip tech", `${t.tech} (${t.count}${t.recent ? ", " + t.recent + " last 7d" : ""}${t.new_count ? ", " + t.new_count + " new" : ""})`);
      chip.href = `/jobs?tech=${encodeURIComponent(t.tech)}`;
      techs.appendChild(chip);
    });
  } catch (err) {
    if (err.status === 503) return;
    console.error(err);
  }
}

// ─── jobs ─────────────────────────────────────────────────
const jobState = { offset: 0, total: 0, loading: false };
const multiIds = ["f-search-title", "f-location", "f-site", "f-experience", "f-tech"];

function multiValue(id) {
  return Array.from(document.getElementById(id).selectedOptions)
    .map((o) => o.value).filter(Boolean).join(",");
}

function setMultiValue(id, values) {
  const select = document.getElementById(id);
  Array.from(select.options).forEach((o) => (o.selected = values.includes(o.value)));
}

function buildJobQuery() {
  const p = new URLSearchParams();
  const set = (k, v) => { if (v) p.set(k, v); };
  set("search_title", multiValue("f-search-title"));
  set("location", multiValue("f-location"));
  set("site", multiValue("f-site"));
  set("experience", multiValue("f-experience"));
  set("tech", multiValue("f-tech"));
  set("company", document.getElementById("f-company").value.trim());
  set("q", document.getElementById("f-q").value.trim());
  if (document.getElementById("f-remote").checked) set("remote", "1");
  if (document.getElementById("f-new").checked) set("new", "1");
  set("date_from", document.getElementById("f-date-from").value);
  set("date_to", document.getElementById("f-date-to").value);
  set("sort", document.getElementById("f-sort").value);
  set("order", document.getElementById("f-order").dataset.order || "desc");
  return p.toString();
}

async function loadJobs(reset) {
  if (jobState.loading) return;
  jobState.loading = true;
  if (reset) jobState.offset = 0;
  const params = buildJobQuery();
  try {
    const data = await api(`/api/jobs?limit=50&offset=${jobState.offset}&${params}`);
    jobState.total = data.total;
    const list = document.getElementById("jobs-list");
    if (reset) list.innerHTML = "";
    data.items.forEach((job) => list.appendChild(jobRow(job)));
    document.getElementById("jobs-meta").textContent =
      `Showing ${Math.min(jobState.offset + data.items.length, data.total)} of ${data.total} jobs`;
    const more = document.getElementById("jobs-more");
    more.classList.toggle("hidden", jobState.offset + data.items.length >= data.total);
    jobState.offset += data.items.length;
  } catch (err) {
    console.error(err);
  } finally {
    jobState.loading = false;
  }
}

function jobRow(job) {
  const row = el("div", "row");
  const title = el("div", "row-title", job.title);
  row.appendChild(title);
  row.appendChild(el("div", "row-sub",
    `${job.company} · ${job.location || "?"} · ${job.site} · posted ${fmtDate(job.date_posted)}`));
  const line = el("div", "row-line");
  if (job.experience_level)
    line.appendChild(el("span", "chip level " + job.experience_level, job.experience_level));
  if (job.is_new === 1) line.appendChild(el("span", "chip new", "NEW"));
  if (job.is_remote === 1) line.appendChild(el("span", "chip remote", "remote"));
  if (job.company_relevance > 1)
    line.appendChild(el("span", "badge", `relevance ${job.company_relevance}`));
  (job.tech_stack || "").split("|").filter(Boolean).slice(0, 4).forEach((t) => {
    line.appendChild(el("span", "chip tech", t));
  });
  row.appendChild(line);
  row.addEventListener("click", () => openJobModal(job.row_id));
  return row;
}

async function openJobModal(rowId) {
  const job = await api(`/api/jobs/${rowId}`);
  const root = document.getElementById("modal-root");
  const overlay = el("div", "modal-overlay");
  const modal = el("div", "modal");

  const close = el("button", "btn btn-small modal-close", "×");
  close.addEventListener("click", () => overlay.remove());
  modal.appendChild(close);

  modal.appendChild(el("h3", null, job.title));
  modal.appendChild(el("div", "row-sub",
    `${job.company} · ${job.location || "?"} · ${job.site} · posted ${fmtDate(job.date_posted)}`));

  const chips = el("div", "chip-row");
  const yearsVal = job.experience_years && job.experience_years !== "0"
    ? `${job.experience_years}+ yrs` : null;
  if (job.experience_level)
    chips.appendChild(el("span", "chip level " + job.experience_level,
      job.experience_level + (yearsVal ? ` · ${yearsVal}` : "")));
  if (job.is_new === 1) chips.appendChild(el("span", "chip new", "NEW"));
  if (job.is_remote === 1) chips.appendChild(el("span", "chip remote", "remote"));
  (job.tech_stack || "").split("|").filter(Boolean).forEach((t) => {
    chips.appendChild(el("span", "chip tech", t));
  });
  modal.appendChild(chips);

  const apply = el("div", "modal-section");
  apply.appendChild(el("h4", null, "Apply"));
  const applyLine = el("div");
  const link1 = el("a", "btn btn-primary link-btn", "Apply (listing)");
  link1.href = job.job_url; link1.target = "_blank";
  applyLine.appendChild(link1);
  if (job.job_url_direct && job.job_url_direct !== job.job_url) {
    const link2 = el("a", "btn link-btn", "Apply (direct)");
    link2.href = job.job_url_direct; link2.target = "_blank";
    applyLine.appendChild(link2);
  }
  if (job.emails) {
    const mail = el("a", "btn link-btn", `Email: ${job.emails.split("|")[0]}`);
    mail.href = "mailto:" + job.emails.split("|")[0];
    applyLine.appendChild(mail);
  }
  apply.appendChild(applyLine);
  modal.appendChild(apply);

  const company = el("div", "modal-section");
  company.appendChild(el("h4", null, "Company"));
  const kv = el("div", "kv");
  const addKv = (k, v) => {
    if (!v) return;
    kv.appendChild(el("div", "k", k));
    const val = el("div");
    if (k === "Website" && String(v).startsWith("http")) {
      const a = el("a", null, v); a.href = v; a.target = "_blank";
      val.appendChild(a);
    } else {
      val.textContent = v;
    }
    kv.appendChild(val);
  };
  addKv("Experience", [job.experience_level, yearsVal]
    .filter(Boolean).join(" · ") || "Not specified");
  addKv("Industry", job.company_industry);
  addKv("Size", job.company_num_employees);
  addKv("Website", job.company_url);
  addKv("Relevance", job.company_relevance ? `${job.company_relevance} postings for "${job.search_title}"` : null);
  addKv("Searched as", `${job.search_title} in ${job.search_location}`);
  addKv("First seen", fmtDate(job.first_seen));
  addKv("Last seen", fmtDate(job.last_seen));
  company.appendChild(kv);
  modal.appendChild(company);

  if (job.description) {
    const desc = el("div", "modal-section");
    desc.appendChild(el("h4", null, "Description"));
    desc.appendChild(el("div", "description", job.description));
    modal.appendChild(desc);
  }

  overlay.appendChild(modal);
  overlay.addEventListener("click", (ev) => { if (ev.target === overlay) overlay.remove(); });
  root.appendChild(overlay);
}

async function initJobs() {
  try {
    const filters = await api("/api/filters");
    const fill = (id, values) => {
      const select = document.getElementById(id);
      values.forEach((v) => {
        const opt = el("option", null, v);
        opt.value = v;
        select.appendChild(opt);
      });
    };
    fill("f-search-title", filters.search_titles);
    fill("f-location", filters.locations);
    fill("f-site", filters.sites);
    fill("f-experience", filters.experience_levels);
    fill("f-tech", filters.techs);
    const datalist = document.getElementById("company-list");
    filters.companies.forEach((c) => {
      const opt = el("option", null, c);
      opt.value = c;
      datalist.appendChild(opt);
    });
  } catch (err) { /* 503: banner already shown */ }

  const params = new URLSearchParams(location.search);
  const apply = (key, controlId, multi) => {
    const v = params.get(key);
    if (!v) return;
    if (multi) setMultiValue(controlId, v.split(","));
    else document.getElementById(controlId).value = v;
  };
  apply("search_title", "f-search-title", true);
  apply("location", "f-location", true);
  apply("site", "f-site", true);
  apply("experience", "f-experience", true);
  apply("tech", "f-tech", true);
  apply("company", "f-company", false);
  apply("q", "f-q", false);
  if (params.get("remote") === "1") document.getElementById("f-remote").checked = true;
  if (params.get("new") === "1") document.getElementById("f-new").checked = true;
  apply("date_from", "f-date-from", false);
  apply("date_to", "f-date-to", false);
  if (params.get("sort")) document.getElementById("f-sort").value = params.get("sort");
  if (params.get("order")) document.getElementById("f-order").dataset.order = params.get("order");

  document.querySelectorAll(".filter-bar select, .filter-bar input").forEach((input) => {
    input.addEventListener("change", () => loadJobs(true));
  });
  document.getElementById("f-q").addEventListener("input", debounce(() => loadJobs(true), 400));
  document.getElementById("f-order").addEventListener("click", (ev) => {
    const btn = ev.target;
    btn.dataset.order = btn.dataset.order === "asc" ? "desc" : "asc";
    btn.textContent = btn.dataset.order === "asc" ? "↑" : "↓";
    loadJobs(true);
  });
  document.getElementById("f-reset").addEventListener("click", () => {
    location.href = "/jobs";
  });
  document.getElementById("jobs-more").addEventListener("click", () => loadJobs(false));

  await loadJobs(true);
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ─── companies ────────────────────────────────────────────
async function initCompanies() {
  const select = document.getElementById("c-sort");
  const load = async () => {
    const data = await api(`/api/companies?sort=${select.value}&limit=100`);
    const list = document.getElementById("companies-list");
    list.innerHTML = "";
    document.getElementById("companies-meta").textContent = `${data.length} companies`;
    data.forEach((c) => list.appendChild(companyRow(c)));
  };
  select.addEventListener("change", load);
  try { await load(); } catch (err) { if (err.status !== 503) console.error(err); }
}

function companyRow(c) {
  const row = el("div", "row");
  const title = el("div", "row-title", c.company);
  title.appendChild(el("span", "badge", `#${c.rank}`));
  row.appendChild(title);
  const sub = el("div", "row-sub",
    `${c.total} jobs · ${c.recent} last 7d · ${c.new} new · ${c.size_bucket || "size ?"}${c.industry ? " · " + c.industry : ""}`);
  row.appendChild(sub);
  const line = el("div", "row-line");
  (c.top_techs || "").split("|").filter(Boolean).slice(0, 4).forEach((t) => {
    line.appendChild(el("span", "chip tech", t));
  });
  (c.titles || []).slice(0, 6).forEach((t) => {
    const chip = el("span", "chip", `${t.search_title}: ${t.count}`);
    chip.style.cursor = "pointer";
    chip.addEventListener("click", (ev) => {
      ev.stopPropagation();
      location.href = `/jobs?company=${encodeURIComponent(c.company)}&search_title=${encodeURIComponent(t.search_title)}`;
    });
    line.appendChild(chip);
  });
  row.appendChild(line);
  row.addEventListener("click", () => (location.href = `/jobs?company=${encodeURIComponent(c.company)}`));
  return row;
}

// ─── tech ─────────────────────────────────────────────────
async function initTech() {
  const select = document.getElementById("t-sort");
  const load = async () => {
    const data = await api(`/api/tech?sort=${select.value}`);
    const list = document.getElementById("tech-list");
    list.innerHTML = "";
    document.getElementById("tech-meta").textContent = `${data.length} technologies`;
    data.forEach((t) => list.appendChild(techRow(t)));
  };
  select.addEventListener("change", load);
  try { await load(); } catch (err) { if (err.status !== 503) console.error(err); }
}

function techRow(t) {
  const row = el("div", "row");
  const title = el("div", "row-title", t.tech);
  title.appendChild(el("span", "badge",
    `${t.count} jobs${t.recent_count ? " · " + t.recent_count + " last 7d" : ""}${t.new_count ? " · " + t.new_count + " new" : ""}`));
  row.appendChild(title);
  const line = el("div", "row-line");
  const stack = el("div", "bar-stack");
  const order = ["intern", "entry", "junior", "mid", "senior", "lead"];
  const total = order.reduce((s, l) => s + (t.experience[l] || 0), 0) || 1;
  order.forEach((l) => {
    const n = t.experience[l] || 0;
    if (n) {
      const seg = el("span", "bar-" + l);
      seg.style.width = (n / total) * 100 + "%";
      seg.title = `${l}: ${n}`;
      stack.appendChild(seg);
    }
  });
  line.appendChild(stack);
  line.appendChild(el("span", "row-sub",
    order.filter((l) => t.experience[l]).map((l) => `${l} ${t.experience[l]}`).join(" · ")));
  t.top_companies.slice(0, 3).forEach((cname) => {
    line.appendChild(el("span", "chip", cname));
  });
  row.appendChild(line);
  row.addEventListener("click", () => (location.href = `/jobs?tech=${encodeURIComponent(t.tech)}`));
  return row;
}

// ─── settings ─────────────────────────────────────────────
let settingsCfg = null;

function refreshSitesSelect() {
  const present = new Set(
    Array.from(document.querySelectorAll("#sites-list .chip")).map((c) => c.textContent)
  );
  const select = document.getElementById("sites-input");
  select.innerHTML = "";
  (settingsCfg?.allowed_sites || []).filter((s) => !present.has(s)).forEach((s) => {
    const opt = el("option", null, s);
    opt.value = s;
    select.appendChild(opt);
  });
  document.getElementById("sites-add").disabled = select.options.length === 0;
}

function settingsItemRow(listId, value) {
  const row = el("div", "settings-item");
  row.appendChild(el("span", "chip", value));
  const rm = el("button", "btn btn-small", "×");
  rm.addEventListener("click", () => {
    row.remove();
    if (listId === "sites-list") refreshSitesSelect();
  });
  row.appendChild(rm);
  document.getElementById(listId).appendChild(row);
}

function renderSettings(cfg) {
  settingsCfg = cfg;
  ["titles-list", "locations-list", "sites-list"].forEach((id) => {
    document.getElementById(id).innerHTML = "";
  });
  cfg.titles.forEach((v) => settingsItemRow("titles-list", v));
  cfg.locations.forEach((v) => settingsItemRow("locations-list", v));
  cfg.sites.forEach((v) => settingsItemRow("sites-list", v));
  document.getElementById("results-input").value = cfg.results_per_search;
  refreshSitesSelect();
}

function collectSettings() {
  const items = (listId) =>
    Array.from(document.querySelectorAll(`#${listId} .chip`)).map((c) => c.textContent);
  return {
    titles: items("titles-list"),
    locations: items("locations-list"),
    sites: items("sites-list"),
    results_per_search: parseInt(document.getElementById("results-input").value, 10),
  };
}

async function saveConfig() {
  const msg = document.getElementById("settings-save-msg");
  msg.classList.add("hidden");
  try {
    const cfg = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectSettings()),
    });
    renderSettings(cfg);
    msg.textContent = "Config saved — applies to the next scrape.";
    msg.classList.remove("hidden");
  } catch (err) {
    alert("Failed to save config: " + err.message);
  }
}

async function startClean() {
  const weeks = parseInt(document.getElementById("clean-weeks").value, 10);
  if (!(weeks >= 1 && weeks <= 52)) return;
  if (!confirm(
    `Delete posts older than ${weeks} weeks?\nRaw + output CSVs are removed and the seen log is purged to the remaining window — purged jobs can reappear as NEW.`
  )) return;
  setRunButtonsDisabled(true);
  try {
    const run = await api("/api/clean", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ weeks }),
    });
    connectStream(run.id, run.label);
    refreshStatus();
  } catch (err) {
    if (err.status === 409) alert("A run is already active — wait for it to finish.");
    else alert("Failed to start clean: " + err.message);
  } finally {
    setRunButtonsDisabled(false);
  }
}

async function initSettings() {
  try {
    const cfg = await api("/api/config");
    renderSettings(cfg);
  } catch (err) {
    console.error(err);
  }
  const bindAdd = (inputId, btnId, listId) => {
    const add = () => {
      const input = document.getElementById(inputId);
      const v = input.value.trim();
      if (!v) return;
      settingsItemRow(listId, v);
      input.value = "";
      if (listId === "sites-list") refreshSitesSelect();
    };
    document.getElementById(btnId).addEventListener("click", add);
    document.getElementById(inputId).addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); add(); }
    });
  };
  bindAdd("titles-input", "titles-add", "titles-list");
  bindAdd("locations-input", "locations-add", "locations-list");
  bindAdd("sites-input", "sites-add", "sites-list");
  document.getElementById("btn-save-config").addEventListener("click", saveConfig);
  const weeksInput = document.getElementById("clean-weeks");
  const cleanBtn = document.getElementById("btn-clean");
  weeksInput.addEventListener("input", () => {
    const w = parseInt(weeksInput.value, 10);
    cleanBtn.disabled = !(w >= 1 && w <= 52);
  });
  cleanBtn.addEventListener("click", startClean);
}

// ─── boot ─────────────────────────────────────────────────
function refreshPage() {
  const page = document.body.dataset.page;
  if (page === "dashboard") loadDashboard();
  else if (page === "jobs") loadJobs(true);
  else if (page === "companies") initCompanies();
  else if (page === "tech") initTech();
  else if (page === "settings") initSettings();
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  document.querySelector(`nav a[data-nav="${page}"]`).classList.add("active");
  document.getElementById("btn-enrich").addEventListener("click", () => startRun("enrich"));
  document.getElementById("btn-scrape24").addEventListener("click", () => startRun("24h"));
  document.getElementById("btn-scrape7d").addEventListener("click", () => startRun("7d"));
  document.getElementById("btn-log").addEventListener("click", () => drawer().classList.toggle("hidden"));
  document.getElementById("btn-log-close").addEventListener("click", () => drawer().classList.add("hidden"));
  refreshStatus();
  if (page === "dashboard") loadDashboard();
  else if (page === "jobs") initJobs();
  else if (page === "companies") initCompanies();
  else if (page === "tech") initTech();
  else if (page === "settings") initSettings();
});
