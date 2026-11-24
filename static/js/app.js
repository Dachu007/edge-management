/* AI-Augmented Edge Resource Manager - front-end */
const NODE_COLORS = { N1: "#2563eb", N2: "#16a34a", N3: "#dc2626", N4: "#d97706", N5: "#7c3aed" };
const POLICY_COLORS = { fixed: "#94a3b8", round_robin: "#f59e0b", least_loaded: "#06b6d4", threshold: "#8b5cf6", ai: "#2563eb" };
const TYPE_COLORS = { traffic: "#2563eb", surveillance: "#7c3aed", emergency: "#dc2626", environment: "#16a34a" };

let META = null;
let STATE = null;
let running = false;
let timer = null;
const charts = {};

// ------------------------------------------------------------ helpers
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(d));

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opt);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

function table(el, cols, rows, rowClass) {
  const head = "<tr>" + cols.map((c) => `<th>${c.h}</th>`).join("") + "</tr>";
  const body = rows.map((r) => `<tr class="${rowClass ? rowClass(r) : ""}">` +
    cols.map((c) => `<td class="${c.cls || ""}">${c.f ? c.f(r) : r[c.k] ?? "—"}</td>`).join("") + "</tr>").join("");
  el.innerHTML = head + body;
}

function makeChart(id, type, data, options = {}) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), {
    type, data,
    options: Object.assign({ responsive: true, animation: false, plugins: { legend: { labels: { boxWidth: 12 } } } }, options),
  });
  return charts[id];
}

const typeLabel = (t) => (META ? META.task_profiles[t].label : t);
const statusBadge = (s) => {
  const map = { ok: "ok", stale: "bad", missing: "warn", unavailable: "bad" };
  return `<span class="badge ${map[s] || "info"}">${s}</span>`;
};

// ------------------------------------------------------------ navigation
$$("nav a").forEach((a) => a.addEventListener("click", (e) => {
  e.preventDefault();
  $$("nav a").forEach((x) => x.classList.remove("active"));
  a.classList.add("active");
  $$(".view").forEach((v) => v.classList.remove("active"));
  $("#view-" + a.dataset.view).classList.add("active");
  if (a.dataset.view === "log") renderLog();
}));

// ------------------------------------------------------------ dashboard
function renderState(s) {
  STATE = s;
  $("#clock").textContent = fmt(s.clock_s, 1);
  const sm = s.summary;
  const kpis = [
    ["Tasks processed", sm.tasks_total],
    ["Deadline success", fmt(sm.deadline_success_pct, 1) + "%"],
    ["Avg completion", fmt(sm.avg_completion_ms, 0) + " ms"],
    ["Deferred", sm.tasks_deferred],
    ["Energy (est.)", fmt(sm.total_energy_wh, 2) + " Wh"],
    ["Decision time", fmt(sm.avg_decision_us, 0) + " µs"],
  ];
  $("#kpis").innerHTML = kpis.map(([l, v]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");

  $("#nodes").innerHTML = s.nodes.map((n) => {
    const cpu = n.cpu_util === null ? null : n.cpu_util * 100;
    const mem = n.mem_used_gb === null ? null : (n.mem_used_gb / n.memory_gb) * 100;
    const cls = (v) => (v === null ? "" : v >= 90 ? "hot" : v >= 60 ? "mid" : "");
    let badge = statusBadge(n.status);
    if (n.overloaded) badge = `<span class="badge bad">overloaded</span>`;
    if (!n.online && n.status === "ok") badge = `<span class="badge warn">offline</span>`;
    return `<div class="node ${n.overloaded ? "overloaded" : ""} ${n.status}">
      <div class="node-head"><span class="node-id" style="color:${NODE_COLORS[n.node_id]}">${n.node_id}</span>${badge}</div>
      <div class="node-name">${n.name}</div>
      <div class="metric"><span>CPU</span><b>${fmt(cpu, 0)}%</b></div>
      <div class="bar ${cls(cpu)}"><span style="width:${cpu ?? 0}%"></span></div>
      <div class="metric"><span>Memory</span><b>${fmt(n.mem_used_gb, 1)} / ${n.memory_gb} GB</b></div>
      <div class="bar ${cls(mem)}"><span style="width:${mem ?? 0}%"></span></div>
      <div class="metric"><span>Queue</span><b>${n.queue_len ?? "—"} tasks</b></div>
      <div class="metric"><span>Queue delay</span><b>${fmt(n.est_wait_ms, 0)} ms</b></div>
      <div class="metric"><span>Bandwidth</span><b>${n.bandwidth_mbps} Mbps</b></div>
      <div class="metric"><span>Latency</span><b>${n.latency_ms} ms</b></div>
      <div class="metric"><span>Power (est.)</span><b>${fmt(n.power_w, 0)} W</b></div>
      <div class="metric"><span>Tasks assigned</span><b>${n.tasks_assigned}</b></div>
    </div>`;
  }).join("");

  // live charts
  const labels = s.series.map((p) => p.t + "s");
  const ids = s.nodes.map((n) => n.node_id);
  const ds = (key) => ids.map((id) => ({
    label: id, data: s.series.map((p) => p[key][id]), borderColor: NODE_COLORS[id],
    backgroundColor: NODE_COLORS[id], tension: 0.3, pointRadius: 0, borderWidth: 2, spanGaps: false,
  }));
  updateLine("chart-live-cpu", labels, ds("cpu"), { min: 0, max: 100 });
  updateLine("chart-live-power", labels, ds("power"), { min: 0 });

  table($("#tbl-recent"), [
    { h: "Task", k: "task_id" },
    { h: "Type", f: (r) => `<span style="color:${TYPE_COLORS[r.task_type]}">${typeLabel(r.task_type)}</span>` },
    { h: "Node", f: (r) => r.deferred ? `<span class="badge warn">deferred</span>` : `<b style="color:${NODE_COLORS[r.node_id]}">${r.node_id}</b>` },
    { h: "Completion", f: (r) => r.deferred ? "—" : fmt(r.completion_ms, 0) + " ms" },
    { h: "Deadline", f: (r) => r.met ? `<span class="yes">met</span>` : `<span class="no">missed</span>` },
    { h: "Policy", f: (r) => r.policy_used + (r.fallback ? " ⚠" : "") },
  ], s.recent);

  $("#events").innerHTML = s.events.length
    ? s.events.map((e) => `<li><span class="t">${fmt(e.time_ms / 1000, 1)}s</span><span class="badge ${e.kind === "fallback" || e.kind === "deferral" ? "warn" : "info"}">${e.kind}</span> ${e.message}</li>`).join("")
    : `<li class="muted">No events yet.</li>`;

  renderAdmin(s);
}

function updateLine(id, labels, datasets, yopts) {
  const c = charts[id];
  if (c) {
    c.data.labels = labels;
    c.data.datasets = datasets;
    c.update("none");
  } else {
    makeChart(id, "line", { labels, datasets }, { scales: { y: yopts } });
  }
}

function renderAdmin(s) {
  const box = $("#admin-nodes");
  box.innerHTML = s.nodes.map((n) => `<div class="admin-node">
      <b style="color:${NODE_COLORS[n.node_id]}">${n.node_id}</b> <span class="muted">${n.name}</span> ${statusBadge(n.status)}
      <label><input type="checkbox" data-node="${n.node_id}" data-k="online" ${n.online ? "checked" : ""}> Online / reporting</label>
      <label><input type="checkbox" data-node="${n.node_id}" data-k="report_missing" ${n.report_missing ? "checked" : ""}> Send missing values</label>
    </div>`).join("");
  box.querySelectorAll("input").forEach((inp) => inp.addEventListener("change", async () => {
    const st = await api(`/api/node/${inp.dataset.node}`, { [inp.dataset.k]: inp.checked });
    renderState(st);
    toast(`${inp.dataset.node} updated`);
  }));
}

async function step(n = 1) {
  const s = await api("/api/tick", { steps: n });
  renderState(s);
}

$("#btn-run").addEventListener("click", () => {
  running = !running;
  $("#btn-run").textContent = running ? "⏸ Pause" : "▶ Start";
  if (running) {
    timer = setInterval(() => step(1).catch(console.error), 1000);
    step(1);
  } else clearInterval(timer);
});
$("#btn-step").addEventListener("click", () => step(1));
$("#btn-reset").addEventListener("click", async () => {
  Object.keys(charts).filter((k) => k.startsWith("chart-live")).forEach((k) => { charts[k].destroy(); delete charts[k]; });
  renderState(await api("/api/reset", {}));
  toast("Live system reset");
});

async function sendConfig(body) {
  renderState(await api("/api/config", body));
}
$("#cfg-policy").addEventListener("change", (e) => sendConfig({ policy: e.target.value }));
$("#cfg-learning").addEventListener("change", (e) => {
  sendConfig({ learning_enabled: e.target.checked });
  toast(e.target.checked ? "AI policy enabled" : "AI disabled → fallback rule (TC07)");
});
$("#cfg-burst").addEventListener("change", (e) => sendConfig({ burst: e.target.checked }));
$("#cfg-rate").addEventListener("input", (e) => ($("#cfg-rate-val").textContent = Number(e.target.value).toFixed(1) + "×"));
$("#cfg-rate").addEventListener("change", (e) => sendConfig({ rate_scale: Number(e.target.value) }));
$("#cfg-energy").addEventListener("input", (e) => ($("#cfg-energy-val").textContent = Number(e.target.value).toFixed(2)));
$("#cfg-energy").addEventListener("change", (e) => sendConfig({ energy_weight: Number(e.target.value) }));

// ------------------------------------------------------------ submit task
function updateHint() {
  const p = META.task_profiles[$("#f-type").value];
  $("#f-hint").innerHTML = `Defaults: work ${p.work[0]}–${p.work[1]} MI · memory ${p.mem[0]}–${p.mem[1]} GB · data ${p.data[0]}–${p.data[1]} MB · ` +
    `min bandwidth ${p.min_bw} Mbps · priority ${META.priority_labels[p.priority]} · deadline ${p.deadline} ms`;
}

async function submitTask(body) {
  const res = await api("/api/task", body);
  const d = res.decision;
  renderState(res.state);
  const t = d.task;
  let html;
  if (d.deferred) {
    html = `<div class="big no">Task #${d.task_id} deferred</div><div>${d.reason}</div>`;
  } else {
    html = `<div class="big">Task #${d.task_id} → <span style="color:${NODE_COLORS[d.node_id]}">${d.node_id}</span></div>
      <div>${t.label} · priority <b>${t.priority_label}</b> · deadline ${t.deadline_ms} ms</div>
      <div>Network ${fmt(d.net_ms)} ms + queue ${fmt(d.wait_ms)} ms + processing ${fmt(d.exec_ms)} ms =
      <b>${fmt(d.completion_ms)} ms</b> ${d.met ? '<span class="yes">✔ deadline met</span>' : '<span class="no">✘ deadline missed</span>'}</div>
      <div class="muted">Policy: ${d.policy_used}${d.fallback ? " (fallback)" : ""} · energy ${fmt(d.energy_j, 2)} J (est.) · decision ${fmt(d.decision_us, 0)} µs</div>`;
  }
  $("#decision").innerHTML = html;
  $("#decision").classList.remove("muted");
  table($("#tbl-trace"), [
    { h: "Node", f: (r) => `<b style="color:${NODE_COLORS[r.node_id]}">${r.node_id}</b> ${r.name}` },
    { h: "Status", f: (r) => statusBadge(r.status) + (r.overloaded ? ' <span class="badge bad">overloaded</span>' : "") },
    { h: "Est. completion", f: (r) => (r.est_completion_ms === null ? "—" : fmt(r.est_completion_ms) + " ms") },
    { h: "Meets deadline", f: (r) => (r.deadline_ok === null ? "—" : r.deadline_ok ? '<span class="yes">yes</span>' : '<span class="no">no</span>') },
    { h: "Q-score", f: (r) => (r.score === null ? "—" : fmt(r.score, 3)) },
    { h: "Reason", f: (r) => r.reason, cls: "wrap" },
  ], d.trace || [], (r) => (r.node_id === d.node_id ? "best" : ""));
}

$("#task-form").addEventListener("submit", (e) => {
  e.preventDefault();
  submitTask(Object.fromEntries(new FormData(e.target).entries())).catch((err) => toast(err.message));
});
$$("[data-quick]").forEach((b) => b.addEventListener("click", () => {
  const q = b.dataset.quick;
  const body = q === "emergency" ? { task_type: "emergency" }
    : q === "bigmem" ? { task_type: "surveillance", memory_gb: 128 }
    : { task_type: "surveillance", work_mi: 3000, data_mb: 20 };
  submitTask(body);
}));

// ------------------------------------------------------------ compare
let SIM = null;
$("#btn-simulate").addEventListener("click", async () => {
  const btn = $("#btn-simulate");
  btn.disabled = true;
  $("#sim-status").textContent = "Running simulation…";
  try {
    const policies = [...$$("#sim-policies input:checked")].map((i) => i.value);
    SIM = await api("/api/simulate", {
      duration_s: Number($("#sim-duration").value), seed: Number($("#sim-seed").value),
      rate_scale: Number($("#sim-rate").value), burst: $("#sim-burst").checked,
      energy_weight: Number($("#sim-energy").value), policies,
    });
    renderCompare();
    $("#sim-status").textContent = `${SIM.tasks} tasks simulated per policy.`;
  } catch (err) {
    $("#sim-status").textContent = "Error: " + err.message;
  }
  btn.disabled = false;
});

function renderCompare() {
  $("#sim-results").classList.remove("hidden");
  const ps = Object.keys(SIM.results);
  const R = SIM.results;
  const best = ps.reduce((a, b) => (R[a].deadline_success_pct > R[b].deadline_success_pct ||
    (R[a].deadline_success_pct === R[b].deadline_success_pct && R[a].avg_completion_ms < R[b].avg_completion_ms) ? a : b));
  table($("#tbl-compare"), [
    { h: "Policy", f: (p) => `<b style="color:${POLICY_COLORS[p]}">${R[p].label}</b>` },
    { h: "Avg completion (ms)", f: (p) => fmt(R[p].avg_completion_ms) },
    { h: "P95 (ms)", f: (p) => fmt(R[p].p95_completion_ms) },
    { h: "Deadline success", f: (p) => fmt(R[p].deadline_success_pct, 2) + "%" },
    { h: "Emergency success", f: (p) => fmt((R[p].per_type.emergency || {}).deadline_success, 2) + "%" },
    { h: "Deferred", f: (p) => R[p].tasks_deferred },
    { h: "Util. imbalance (σ)", f: (p) => fmt(R[p].utilisation_imbalance, 2) },
    { h: "Task energy (Wh)", f: (p) => fmt(R[p].task_energy_wh, 3) },
    { h: "Total energy (Wh)", f: (p) => fmt(R[p].total_energy_wh, 2) },
    { h: "Decision (µs)", f: (p) => fmt(R[p].avg_decision_us, 0) },
  ], ps, (p) => (p === best ? "best" : ""));

  $("#downloads").innerHTML = '<span class="muted">Download decision log (CSV):</span>' +
    ps.map((p) => `<a href="/api/report.csv?policy=${p}">${R[p].label}</a>`).join(" · ");

  const labels = ps.map((p) => R[p].label);
  const colors = ps.map((p) => POLICY_COLORS[p]);
  makeChart("chart-time", "bar", { labels, datasets: [
    { label: "Average", data: ps.map((p) => R[p].avg_completion_ms), backgroundColor: colors },
    { label: "P95", data: ps.map((p) => R[p].p95_completion_ms), backgroundColor: colors.map((c) => c + "66") },
  ] });
  makeChart("chart-deadline", "bar", { labels, datasets: [{ label: "Deadline success %", data: ps.map((p) => R[p].deadline_success_pct), backgroundColor: colors }] },
    { plugins: { legend: { display: false } }, scales: { y: { min: Math.max(0, Math.min(...ps.map((p) => R[p].deadline_success_pct)) - 10), max: 100 } } });
  makeChart("chart-energy", "bar", { labels, datasets: [{ label: "Task energy (Wh)", data: ps.map((p) => R[p].task_energy_wh), backgroundColor: colors }] },
    { plugins: { legend: { display: false } } });
  const nodeIds = Object.keys(R[ps[0]].node_utilisation_pct);
  makeChart("chart-util", "bar", { labels, datasets: nodeIds.map((n) => ({
    label: n, data: ps.map((p) => R[p].node_utilisation_pct[n]), backgroundColor: NODE_COLORS[n] })) });
  const types = Object.keys(META.task_profiles);
  makeChart("chart-pertype", "bar", { labels: types.map(typeLabel), datasets: ps.map((p) => ({
    label: R[p].label, data: types.map((t) => (R[p].per_type[t] || {}).deadline_success ?? 0), backgroundColor: POLICY_COLORS[p] })) },
    { scales: { y: { max: 100 } } });

  const sel = $("#tl-policy");
  sel.innerHTML = ps.map((p) => `<option value="${p}">${R[p].label}</option>`).join("");
  sel.value = ps.includes("ai") ? "ai" : ps[0];
  sel.onchange = renderTimeline;
  renderTimeline();
}

function renderTimeline() {
  const tl = SIM.timelines[$("#tl-policy").value];
  makeChart("chart-timeline", "line", { labels: tl.seconds.map((s) => s + "s"), datasets: Object.keys(tl.util).map((n) => ({
    label: n, data: tl.util[n], borderColor: NODE_COLORS[n], backgroundColor: NODE_COLORS[n], pointRadius: 0, tension: 0.3, borderWidth: 2 })) },
    { scales: { y: { min: 0, max: 100, title: { display: true, text: "CPU %" } } } });
}

// ------------------------------------------------------------ training
function renderTrainCurve(curve) {
  if (!curve || !curve.length) {
    $("#agent-info").textContent = `Loaded saved Q-table (${META.agent.states} state-action entries, ${META.agent.episodes} episodes). Click "Train agent" to retrain and see the learning curve.`;
    return;
  }
  makeChart("chart-train", "line", { labels: curve.map((c) => c.episode), datasets: [
    { label: "Deadline success %", data: curve.map((c) => c.deadline_success_pct), borderColor: "#16a34a", backgroundColor: "#16a34a", yAxisID: "y", pointRadius: 0, tension: 0.3 },
    { label: "Avg completion (ms)", data: curve.map((c) => c.avg_completion_ms), borderColor: "#2563eb", backgroundColor: "#2563eb", yAxisID: "y1", pointRadius: 0, tension: 0.3 },
  ] }, { scales: { x: { title: { display: true, text: "Episode" } }, y: { position: "left" }, y1: { position: "right", grid: { drawOnChartArea: false } } } });
}

$("#btn-train").addEventListener("click", async () => {
  const btn = $("#btn-train");
  btn.disabled = true;
  $("#train-status").textContent = "Training… (a few seconds)";
  try {
    const r = await api("/api/train", { episodes: Number($("#train-eps").value), energy_weight: Number($("#train-energy").value) });
    renderTrainCurve(r.curve);
    $("#train-status").textContent = `Done: ${r.states} state-action entries learned.`;
    $("#agent-info").textContent = "";
    toast("Agent trained and saved");
  } catch (err) {
    $("#train-status").textContent = "Error: " + err.message;
  }
  btn.disabled = false;
});

// ------------------------------------------------------------ tests
$("#btn-tests").addEventListener("click", async () => {
  const rows = await api("/api/tests");
  const passed = rows.filter((r) => r.passed).length;
  table($("#tbl-tests"), [
    { h: "Test ID", k: "id" },
    { h: "Module", k: "module" },
    { h: "Test case / action", k: "action", cls: "wrap" },
    { h: "Expected result", k: "expected", cls: "wrap" },
    { h: "Actual result", k: "actual", cls: "wrap" },
    { h: "Pass / Fail", f: (r) => (r.passed ? '<span class="badge ok">PASS</span>' : '<span class="badge bad">FAIL</span>') },
  ], rows);
  toast(`${passed}/${rows.length} tests passed`);
});

// ------------------------------------------------------------ log
async function renderLog() {
  const s = await api("/api/state");
  table($("#tbl-log"), [
    { h: "Task", k: "task_id" },
    { h: "Arrival (s)", f: (r) => fmt(r.arrival_ms / 1000, 2) },
    { h: "Type", f: (r) => typeLabel(r.task_type) },
    { h: "Priority", f: (r) => META.priority_labels[r.priority] },
    { h: "Node", f: (r) => r.node_id || "—" },
    { h: "Network (ms)", f: (r) => fmt(r.net_ms) },
    { h: "Queue (ms)", f: (r) => fmt(r.wait_ms) },
    { h: "Exec (ms)", f: (r) => fmt(r.exec_ms) },
    { h: "Completion (ms)", f: (r) => fmt(r.completion_ms) },
    { h: "Deadline (ms)", k: "deadline_ms" },
    { h: "Met", f: (r) => (r.met ? '<span class="yes">yes</span>' : '<span class="no">no</span>') },
    { h: "Energy (J)", f: (r) => fmt(r.energy_j, 2) },
    { h: "Policy", f: (r) => r.policy_used + (r.fallback ? " (fallback)" : "") },
    { h: "Reason", k: "reason" },
  ], s.recent);
}
$("#btn-log-refresh").addEventListener("click", renderLog);

// ------------------------------------------------------------ init
(async function init() {
  META = await api("/api/meta");
  const pol = Object.entries(META.policies);
  $("#cfg-policy").innerHTML = pol.map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  $("#sim-policies").innerHTML = pol.map(([k, v]) => `<label><input type="checkbox" value="${k}" checked> ${v}</label>`).join("");
  $("#f-type").innerHTML = Object.entries(META.task_profiles).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("");
  $("#f-type").addEventListener("change", updateHint);
  updateHint();

  table($("#tbl-infra"), [
    { h: "Node", f: (n) => `<b style="color:${NODE_COLORS[n.node_id]}">${n.node_id}</b> ${n.name}` },
    { h: "Cores × MIPS", f: (n) => `${n.cores} × ${n.mips}` },
    { h: "Memory", f: (n) => n.memory_gb + " GB" },
    { h: "Bandwidth", f: (n) => n.bandwidth_mbps + " Mbps" },
    { h: "Latency", f: (n) => n.latency_ms + " ms" },
    { h: "Power", f: (n) => `${n.idle_w}–${n.max_w} W` },
  ], META.nodes);
  table($("#tbl-workloads"), [
    { h: "Application", f: ([k, p]) => `<span style="color:${TYPE_COLORS[k]}">${p.label}</span>` },
    { h: "Priority", f: ([, p]) => META.priority_labels[p.priority] },
    { h: "Deadline", f: ([, p]) => p.deadline + " ms" },
    { h: "Work (MI)", f: ([, p]) => p.work.join("–") },
    { h: "Data (MB)", f: ([, p]) => p.data.join("–") },
    { h: "Rate", f: ([, p]) => p.rate + "/s" },
    { h: "Home node", f: ([k]) => META.fixed_map[k] },
  ], Object.entries(META.task_profiles));

  renderTrainCurve(META.train_curve);
  renderState(await api("/api/state"));
})();
