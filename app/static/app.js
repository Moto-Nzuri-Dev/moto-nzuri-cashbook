/* Moto Nzuri Cashbook — browser app. Talks to the FastAPI backend under /api. */
"use strict";

/* ---------------------------------------------------------------- helpers */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const KES = n => "KES " + Number(n).toLocaleString("en-KE", {minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2});
const kb = b => b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.round(b / 1024) + " KB";
const today = () => new Date().toLocaleDateString("en-CA", {timeZone: "Africa/Nairobi"});
const fmtDate = d => new Date(d + (d.length === 10 ? "T12:00:00" : "")).toLocaleDateString("en-GB", {day: "numeric", month: "short", year: "numeric"});
const fmtTime = d => new Date(d).toLocaleString("en-GB", {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Africa/Nairobi"});
const STATUS = {OPEN: ["OPEN", "p-warn"], SUBMITTED: ["AWAITING BOSS", "p-info"], APPROVED: ["APPROVED", "p-ok"], QUERIED: ["QUERIED", "p-bad"],
                SENT: ["SENT", "p-info"], DECLINED: ["DECLINED", "p-bad"], NOTED: ["NOTED", "p-ok"]};
const pill = s => `<span class="pill ${STATUS[s][1]}">${STATUS[s][0]}</span>`;
const locked = f => f.status === "SUBMITTED" || f.status === "APPROVED";

let ME = null, CATS = [], THRESHOLD = 500;

function toast(msg, err) {
  document.querySelectorAll(".toast").forEach(t => t.remove());
  const d = document.createElement("div");
  d.className = "toast" + (err ? " err" : "");
  d.textContent = msg;
  document.body.appendChild(d);
  setTimeout(() => d.remove(), err ? 5000 : 3200);
}

async function api(path, opts = {}) {
  const o = {method: opts.method || "GET", headers: {"x-cashbook": "1"}, credentials: "same-origin"};
  if (opts.form) o.body = opts.form;
  else if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
  let r;
  try { r = await fetch(path, o); } catch (e) { throw new Error("No connection to the server. Check your internet and try again."); }
  if (r.status === 401 && !path.startsWith("/api/auth/")) { ME = null; boot(); throw new Error("Please sign in again."); }
  const data = (r.headers.get("content-type") || "").includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error((data && data.detail) || "Something went wrong (" + r.status + ").");
  return data;
}
const run = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
const post = (p, body) => api(p, {method: "POST", body});

/* ---------------------------------------------------------------- photo compression (in the phone, before upload) */
function compress(file, targetKB = 200) {
  return new Promise((res, rej) => {
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = async () => {
      let max = 1600, q = 0.78, blob = null;
      const c = document.createElement("canvas"), x = c.getContext("2d");
      for (let pass = 0; pass < 9; pass++) {
        const s = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
        c.width = Math.round(img.naturalWidth * s); c.height = Math.round(img.naturalHeight * s);
        x.fillStyle = "#fff"; x.fillRect(0, 0, c.width, c.height); x.drawImage(img, 0, 0, c.width, c.height);
        blob = await new Promise(r => c.toBlob(r, "image/jpeg", q));
        if (blob && blob.size <= targetKB * 1024) break;
        if (q > 0.5) q -= 0.1; else max = Math.round(max * 0.8);
      }
      URL.revokeObjectURL(url);
      blob ? res(blob) : rej(new Error("Couldn't read that photo."));
    };
    img.onerror = () => { URL.revokeObjectURL(url); rej(new Error("That file is not a photo we can read.")); };
    img.src = url;
  });
}
async function uploadPhoto(path, file, extra = {}) {
  const blob = await compress(file);
  const fd = new FormData();
  fd.append("file", blob, "photo.jpg");
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  const out = await api(path, {method: "POST", form: fd});
  return {out, before: file.size, after: blob.size};
}

/* ---------------------------------------------------------------- sheets (pop-ups) */
const modal = $("m"), mBody = $("mBody");
modal.addEventListener("click", e => { if (e.target === modal) closeSheet(); });
function openSheet(html) { mBody.innerHTML = html; modal.classList.add("open"); mBody.scrollTop = 0; }
function closeSheet() { modal.classList.remove("open"); }
document.addEventListener("keydown", e => { if (e.key === "Escape") closeSheet(); });

/* ---------------------------------------------------------------- start-up: setup / login / app */
async function boot() {
  $("nav").classList.add("hide"); $("fab").classList.add("hide"); $("who").classList.add("hide");
  let st;
  try { st = await api("/api/auth/state"); }
  catch (e) { $("main").innerHTML = `<div class="card note bad">${esc(e.message)}</div>`; return; }
  if (st.needs_setup) return showSetup();
  if (!st.user) return showLogin();
  ME = st.user; CATS = st.categories || [];
  const s = await api("/api/settings"); THRESHOLD = s.proof_threshold;
  $("who").textContent = ME.full_name.split(" ")[0] + " · " + ({admin: "Admin", manager: "Manager", boss: "Boss"}[ME.role]);
  $("who").classList.remove("hide");
  route();
}

function showSetup() {
  $("main").innerHTML = `<div class="card auth"><h2>Welcome — first-time setup</h2>
    <div class="sub">Create the administrator account. This screen appears only once.</div>
    <label>Full name</label><input id="sName" autocomplete="name">
    <label>Phone number (used to sign in)</label><input id="sPhone" inputmode="tel" placeholder="0712345678">
    <label>Password (at least 8 characters)</label><input id="sPw" type="password" autocomplete="new-password">
    <label>Repeat password</label><input id="sPw2" type="password" autocomplete="new-password">
    <div class="rowflex" style="margin-top:14px"><button class="btn" id="sGo">Create administrator</button></div></div>`;
  $("sGo").onclick = run(async () => {
    if ($("sPw").value !== $("sPw2").value) throw new Error("The two passwords don't match.");
    await post("/api/auth/setup", {full_name: $("sName").value, phone: $("sPhone").value, password: $("sPw").value});
    toast("Administrator created"); boot();
  });
}

function showLogin() {
  $("main").innerHTML = `<div class="card auth"><h2>Sign in</h2>
    <label>Phone number</label><input id="lPhone" inputmode="tel" autocomplete="username" placeholder="0712345678">
    <label>Password</label><input id="lPw" type="password" autocomplete="current-password">
    <div class="rowflex" style="margin-top:14px"><button class="btn" id="lGo">Sign in</button></div>
    <div class="sub" style="margin-top:10px">Forgot your password? Ask the administrator to reset it.</div></div>`;
  const go = run(async () => { await post("/api/auth/login", {phone: $("lPhone").value, password: $("lPw").value}); boot(); });
  $("lGo").onclick = go;
  $("lPw").onkeydown = e => { if (e.key === "Enter") go(); };
}

$("who").onclick = () => openSheet(`<h2>${esc(ME.full_name)}</h2><div class="sub">${esc(ME.phone)} · ${ME.role}</div>
  <h3>Change password</h3>
  <label>Current password</label><input id="pCur" type="password" autocomplete="current-password">
  <label>New password (at least 8 characters)</label><input id="pNew" type="password" autocomplete="new-password">
  <div class="rowflex" style="margin-top:12px"><button class="btn" onclick="changePw()">Save password</button>
  <button class="btn ghost" onclick="logout()">Sign out</button><button class="btn ghost" onclick="closeSheet()">Close</button></div>`);
const changePw = run(async () => { await post("/api/auth/password", {current_password: $("pCur").value, new_password: $("pNew").value}); closeSheet(); toast("Password changed"); });
const logout = run(async () => { await post("/api/auth/logout", {}); closeSheet(); ME = null; location.hash = ""; boot(); });

/* ---------------------------------------------------------------- navigation */
const TABS = {
  admin:   [["dash", "Dashboard"], ["floats", "Floats"], ["team", "Team"], ["reports", "Field & Office"], ["people", "People"], ["settings", "Settings"]],
  manager: [["dash", "Dashboard"], ["floats", "Floats"], ["reports", "Field & Office"], ["settings", "Settings"]],
  boss:    [["dash", "For approval"], ["floats", "Floats"], ["team", "Team"], ["reports", "Field & Office"], ["settings", "Settings"]],
};
window.addEventListener("hashchange", () => ME && route());
function go(h) { if (location.hash === "#" + h) route(); else location.hash = h; }

function route() {
  const [view, id] = (location.hash.slice(1) || "dash").split("/");
  const tab = {float: "floats", report: "reports"}[view] || view;
  $("nav").innerHTML = TABS[ME.role].map(([v, l]) => `<button data-v="${v}" class="${v === tab ? "on" : ""}">${l}</button>`).join("");
  $("nav").classList.remove("hide");
  $("nav").onclick = e => { const b = e.target.closest("button"); if (b) go(b.dataset.v); };
  $("fab").classList.toggle("hide", ME.role === "boss");
  closeSheet(); window.scrollTo(0, 0);
  const views = {dash: viewDash, floats: viewFloats, float: viewFloat, team: viewTeam, reports: viewReports,
                 report: viewReport, people: viewPeople, settings: viewSettings};
  (views[view] || viewDash)(id ? +id : undefined).catch(e => {
    $("main").innerHTML = `<div class="card note bad">${esc(e.message)}</div>`;
  });
}

/* ---------------------------------------------------------------- dashboard */
async function viewDash() {
  const d = await api("/api/dashboard");
  const floats = await api("/api/floats");
  if (ME.role === "boss") {
    const waiting = floats.filter(f => f.status === "SUBMITTED");
    const reports = (await api("/api/field-reports")).filter(r => r.status === "SENT");
    $("main").innerHTML = `<div class="grid">
      ${kpi("Floats awaiting approval", waiting.length)}${kpi("Reports to read", reports.length)}
      ${kpi("Floats issued", KES(d.all.given))}${kpi("Team balance", KES(d.all.balance), d.all.balance < 0)}</div>
      ${waiting.length ? waiting.map(f => floatCard(f)).join("") : `<div class="card"><h2>No floats waiting</h2><div class="sub">Every submitted float has been reviewed.</div></div>`}
      ${reports.length ? `<div class="card"><h2>New field &amp; office reports</h2>${reports.map(reportRow).join("")}</div>` : ""}`;
    return;
  }
  const m = d.me, mine = floats.filter(f => f.manager_id === ME.id);
  $("main").innerHTML = `<div class="grid">
    ${kpi("Floats received", KES(m.given))}${kpi("Spent", KES(m.spent))}
    ${kpi(m.balance < 0 ? "Overspent" : "Net balance", KES(Math.abs(m.balance)), m.balance < 0, !(m.balance < 0))}
    ${kpi("Proof attached", m.with_proof + "/" + m.expenses)}</div>
    ${mine.filter(f => f.status !== "APPROVED").map(f => floatCard(f)).join("") ||
      `<div class="card"><h2>No open floats</h2><div class="sub">Record a float when you receive money, then add expenses against it.</div>
       <div class="rowflex" style="margin-top:10px"><button class="btn" onclick="newFloat()">Record a float</button></div></div>`}
    ${ME.role === "admin" && d.all.awaiting ? `<div class="note info">${d.all.awaiting} float(s) from the team are waiting for the boss. See <a href="#team">Team</a>.</div>` : ""}`;
}
function kpi(l, v, bad, good) {
  return `<div class="card kpi"><div class="l">${l}</div><div class="v mono-num" style="${bad ? "color:var(--bad)" : good ? "color:var(--ok)" : ""}">${v}</div></div>`;
}

/* ---------------------------------------------------------------- floats */
function floatCard(f) {
  const over = f.balance < 0, pct = f.amount ? Math.min(100, f.spent / f.amount * 100) : 0;
  return `<div class="card clickable" onclick="go('float/${f.id}')"><div class="spread">
    <div><h2 style="margin:0">${esc(f.label)}</h2><div class="sub">${f.code} · ${esc(f.manager)} · from ${esc(f.source)} · ${fmtDate(f.issued_on)}</div></div>
    ${pill(f.status)}</div>
    <div class="bar"><i class="${over ? "over" : ""}" style="width:${pct}%"></i></div>
    <table style="margin-top:8px"><tr><td>Float</td><td class="r">${KES(f.amount)}</td></tr><tr><td>Spent (${f.expense_count})</td><td class="r">${KES(f.spent)}</td></tr>
    <tr><td><b>${over ? "Over by" : "Balance"}</b></td><td class="r"><b style="${over ? "color:var(--bad)" : ""}">${KES(Math.abs(f.balance))}</b></td></tr></table>
    ${f.missing_proof_count && !locked(f) ? `<div class="note bad">${f.missing_proof_count} expense(s) need proof before submitting.</div>` : ""}</div>`;
}

async function viewFloats() {
  const floats = await api("/api/floats");
  const canAdd = ME.role !== "boss";
  $("main").innerHTML = `${canAdd ? `<div class="rowflex" style="margin-bottom:12px"><button class="btn" onclick="newFloat()">+ Record a float</button></div>` : ""}
    ${floats.map(floatCard).join("") || `<div class="card sub">No floats yet.</div>`}`;
}

async function newFloat() {
  let holders = [ME];
  if (ME.role === "admin") holders = (await api("/api/users")).filter(u => u.is_active && u.role !== "boss");
  openSheet(`<h2>Record a float</h2>
    ${holders.length > 1 ? `<label>Manager receiving it</label><select id="fM">${holders.map(u => `<option value="${u.id}" ${u.id === ME.id ? "selected" : ""}>${esc(u.full_name)}</option>`).join("")}</select>` : ""}
    <label>Name</label><input id="fL" placeholder="e.g. Week float 13–18 Sep">
    <div class="two"><div><label>Amount (KES)</label><input id="fA" type="number" inputmode="decimal" min="1"></div>
    <div><label>Date received</label><input id="fD" type="date" value="${today()}" max="${today()}"></div></div>
    <label>Received from</label><input id="fS" value="Boss" placeholder="e.g. Boss, Macharia">
    <div class="rowflex" style="margin-top:14px"><button class="btn" onclick="saveFloat()">Save float</button><button class="btn ghost" onclick="closeSheet()">Cancel</button></div>`);
}
const saveFloat = run(async () => {
  const f = await post("/api/floats", {label: $("fL").value, amount: $("fA").value, issued_on: $("fD").value, source: $("fS").value,
                                        manager_id: $("fM") ? +$("fM").value : undefined});
  closeSheet(); toast("Float saved"); go("float/" + f.id);
});

let CUR = null; // float on screen
async function viewFloat(id) {
  const f = CUR = await api("/api/floats/" + id);
  const mine = f.manager_id === ME.id, editable = mine && !locked(f), over = f.balance < 0;
  const canReview = (ME.role === "boss" || ME.role === "admin") && !mine && f.status === "SUBMITTED";
  const cats = {}; f.expenses.forEach(e => cats[e.category] = (cats[e.category] || 0) + e.total);
  $("main").innerHTML = `<div class="card"><div class="spread">
      <div><h2 style="margin:0">${esc(f.label)}</h2><div class="sub">${f.code} · ${esc(f.manager)} · from ${esc(f.source)} · ${fmtDate(f.issued_on)}</div></div>${pill(f.status)}</div>
    <div class="bar"><i class="${over ? "over" : ""}" style="width:${f.amount ? Math.min(100, f.spent / f.amount * 100) : 0}%"></i></div>
    <table style="margin-top:8px"><tr><td>Float</td><td class="r">${KES(f.amount)}</td></tr>
      <tr><td>Spent (${f.expense_count} expenses, incl. M-Pesa charges)</td><td class="r">${KES(f.spent)}</td></tr>
      <tr><td><b>${over ? "Over by" : "Balance"}</b></td><td class="r"><b style="${over ? "color:var(--bad)" : ""}">${KES(Math.abs(f.balance))}</b></td></tr>
      <tr><td>Proof attached</td><td class="r">${f.proof_count} of ${f.expense_count}</td></tr></table>
    ${f.note ? `<div class="note"><b>Manager's note:</b> ${esc(f.note)}</div>` : ""}
    ${f.reviews.map(r => `<div class="note ${r.decision === "APPROVED" ? "ok" : "bad"}"><b>${r.decision === "APPROVED" ? "Approved" : "Queried"} by ${esc(r.reviewer)} · ${fmtTime(r.at)}</b>${r.comment ? ": " + esc(r.comment) : ""}</div>`).join("")}
    ${f.missing_proof_count && !locked(f) ? `<div class="note bad"><b>${f.missing_proof_count} expense(s) need proof</b> before this float can be submitted (rule: proof for ${KES(THRESHOLD)} and above).</div>` : ""}
    ${locked(f) ? `<div class="lock">🔒 ${f.status === "APPROVED" ? "Approved — locked. No changes allowed." : "Submitted — locked while the boss reviews."}</div>` : ""}
    <div class="rowflex" style="margin-top:12px">
      ${editable ? `<button class="btn" onclick="submitFloat()">${f.status === "QUERIED" ? "Resubmit to boss" : "Submit to boss"}</button>` : ""}
      ${canReview ? `<button class="btn ok" onclick="review('APPROVED')">Approve</button><button class="btn bad" onclick="review('QUERIED')">Query</button>` : ""}
      <a class="btn ghost" href="/api/floats/${f.id}/evidence.pdf" target="_blank" rel="noopener">Evidence pack (PDF)</a>
      <button class="btn ghost" onclick="shareFloat()">Copy for WhatsApp</button>
      ${editable ? `<button class="btn ghost" onclick="editFloat()">Edit float</button>` : ""}
    </div></div>
    <div class="card"><div class="spread"><h2>Expenses</h2>${editable ? `<button class="btn small" onclick="newExpense(${f.id})">+ Add</button>` : ""}</div>
      ${f.expenses.length ? f.expenses.map(txRow).join("") : `<div class="sub">No expenses yet.</div>`}</div>
    ${Object.keys(cats).length ? `<div class="card"><h2>By category</h2><table>${Object.entries(cats).sort((a, b) => b[1] - a[1]).map(([c, a]) => `<tr><td>${esc(c)}</td><td class="r">${KES(a)}</td></tr>`).join("")}</table></div>` : ""}`;
}

function txRow(e) {
  const editable = CUR && CUR.manager_id === ME.id && !locked(CUR);
  let t;
  if (e.proof) t = `<button class="thumb" onclick="showProof(${e.id})"><img loading="lazy" src="/api/expenses/${e.id}/proof?s=${e.proof.size}" alt="proof"></button>`;
  else t = `<button class="thumb none ${e.needs_proof ? "" : "minor"}" ${editable ? `onclick="attachProof(${e.id})"` : "disabled"}>${e.needs_proof ? "Proof<br>needed" : "No<br>proof"}</button>`;
  return `<div class="tx">${t}<div class="m" ${editable ? `onclick="editExpense(${e.id})"` : ""}><div class="n">${esc(e.description)}</div>
    <div class="s">${fmtDate(e.spent_on)} · ${esc(e.category)}${e.mpesa_code ? " · " + e.mpesa_code : ""}</div></div>
    <div class="a mono-num">${KES(e.total)}${e.fee ? `<small>incl. ${KES(e.fee)} charge</small>` : ""}</div></div>`;
}

function editFloat() {
  const f = CUR;
  openSheet(`<h2>Edit float</h2><label>Name</label><input id="eL" value="${esc(f.label)}">
    <div class="two"><div><label>Amount (KES)</label><input id="eA" type="number" inputmode="decimal" value="${f.amount}"></div>
    <div><label>Date received</label><input id="eD" type="date" value="${f.issued_on}" max="${today()}"></div></div>
    <label>Received from</label><input id="eS" value="${esc(f.source)}">
    <div class="rowflex" style="margin-top:14px"><button class="btn" onclick="saveFloatEdit()">Save</button>
    ${f.expense_count ? "" : `<button class="btn bad" onclick="deleteFloat()">Delete float</button>`}
    <button class="btn ghost" onclick="closeSheet()">Cancel</button></div>`);
}
const saveFloatEdit = run(async () => {
  await api("/api/floats/" + CUR.id, {method: "PATCH", body: {label: $("eL").value, amount: $("eA").value, issued_on: $("eD").value, source: $("eS").value}});
  toast("Float updated"); route();
});
const deleteFloat = run(async () => {
  if (!confirm("Delete this float? This can't be undone.")) return;
  await api("/api/floats/" + CUR.id, {method: "DELETE"}); toast("Float deleted"); go("floats");
});

function submitFloat() {
  const f = CUR;
  if (f.missing_proof_count) {
    openSheet(`<h2>Can't submit yet</h2><div class="note bad">These expenses are ${KES(THRESHOLD)} or more and have no proof:</div>
      ${f.expenses.filter(e => e.needs_proof).map(txRow).join("")}
      <div class="sub" style="margin-top:8px">Tap "Proof needed" to attach a photo, then submit again.</div>
      <div style="margin-top:12px"><button class="btn ghost" onclick="closeSheet()">OK</button></div>`);
    return;
  }
  const b = f.balance;
  openSheet(`<h2>Submit ${esc(f.label)}</h2>
    <table><tr><td>Received</td><td class="r">${KES(f.amount)}</td></tr><tr><td>Spent</td><td class="r">${KES(f.spent)}</td></tr>
    <tr><td><b>${b < 0 ? "Over by" : "Balance"}</b></td><td class="r"><b>${KES(Math.abs(b))}</b></td></tr></table>
    <label>Note to boss ${b !== 0 ? "(required — explain the balance or overspend)" : "(optional)"}</label><textarea id="sn" rows="4">${esc(f.note)}</textarea>
    <div class="sub" style="margin-top:6px">After submitting, the float locks until the boss approves or queries it.</div>
    <div class="rowflex" style="margin-top:12px"><button class="btn" onclick="doSubmit()">Submit</button><button class="btn ghost" onclick="closeSheet()">Cancel</button></div>`);
}
const doSubmit = run(async () => { await post(`/api/floats/${CUR.id}/submit`, {note: $("sn").value}); toast("Submitted to boss"); route(); });

function review(decision) {
  const ok = decision === "APPROVED";
  openSheet(`<h2>${ok ? "Approve" : "Query"} ${esc(CUR.label)}</h2>
    <div class="sub">${esc(CUR.manager)} · spent ${KES(CUR.spent)} of ${KES(CUR.amount)}</div>
    <label>Comment ${ok ? "(optional)" : "(required — what needs fixing?)"}</label><textarea id="rc" rows="3"></textarea>
    ${ok ? `<label style="display:flex;gap:8px;align-items:center;color:var(--ink)"><input type="checkbox" id="rConfirm" style="width:auto"> I have checked the expenses and proof</label>` : ""}
    <div class="rowflex" style="margin-top:12px"><button class="btn ${ok ? "ok" : "bad"}" onclick="doReview('${decision}')">${ok ? "Approve & lock" : "Send query"}</button>
    <button class="btn ghost" onclick="closeSheet()">Cancel</button></div>`);
}
const doReview = run(async decision => {
  if (decision === "APPROVED" && !$("rConfirm").checked) throw new Error("Tick the box to confirm you've checked it.");
  await post(`/api/floats/${CUR.id}/review`, {decision, comment: $("rc").value});
  toast(decision === "APPROVED" ? "Approved and locked" : "Query sent to manager"); route();
});

function shareFloat() {
  const f = CUR, b = f.balance;
  const lines = [`*Moto Nzuri – ${f.label}* (${f.code})`, `Manager: ${f.manager}`,
    `Received ${KES(f.amount)} from ${f.source} on ${fmtDate(f.issued_on)}`, `Spent ${KES(f.spent)} on ${f.expense_count} expenses`,
    b < 0 ? `Over by ${KES(-b)}` : `Balance ${KES(b)}`, `Proof attached: ${f.proof_count}/${f.expense_count}`, `Status: ${STATUS[f.status][0]}`];
  if (f.note) lines.push("Note: " + f.note);
  const txt = lines.join("\n");
  (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(
    () => toast("Copied — paste into WhatsApp"), () => openSheet(`<h2>Copy this</h2><textarea rows="9">${esc(txt)}</textarea><div style="margin-top:10px"><button class="btn ghost" onclick="closeSheet()">Close</button></div>`));
}

/* ---------------------------------------------------------------- expenses */
$("fab").onclick = run(async () => {
  const [view, id] = (location.hash.slice(1) || "").split("/");
  if (view === "float" && CUR && CUR.id === +id && CUR.manager_id === ME.id && !locked(CUR)) return newExpense(CUR.id);
  const open = (await api("/api/floats")).filter(f => f.manager_id === ME.id && !locked(f));
  if (!open.length) { toast("You have no open float. Record a float first."); return newFloat(); }
  newExpense(open[0].id, open);
});

async function newExpense(fid, open) {
  open = open || (await api("/api/floats")).filter(f => f.manager_id === ME.id && !locked(f));
  expenseSheet({float_id: fid, spent_on: today(), category: "Transport"}, open);
}
function editExpense(eid) { expenseSheet(CUR.expenses.find(e => e.id === eid)); }

function expenseSheet(e, open) {
  const isNew = !e.id;
  openSheet(`<h2>${isNew ? "Add expense" : "Edit expense"}</h2>
    ${isNew && open && open.length > 1 ? `<label>Float</label><select id="xF">${open.map(f => `<option value="${f.id}" ${f.id === e.float_id ? "selected" : ""}>${esc(f.label)} (${f.code})</option>`).join("")}</select>` : ""}
    ${isNew ? `<label>Paste M-Pesa message (optional)</label><textarea id="xP" rows="3" placeholder="TJK4XY12AB Confirmed. Ksh1,500.00 sent to JOHN BODA on 21/9/26 ... Transaction cost, Ksh23.00"></textarea>
    <button class="btn ghost small" style="margin-top:8px" onclick="readPaste()">Read message</button>` : ""}
    <label>Description</label><input id="xN" value="${esc(e.description || "")}" placeholder="e.g. Boda to Kayole">
    <div class="two"><div><label>Category</label><select id="xC">${CATS.map(c => `<option ${c === e.category ? "selected" : ""}>${c}</option>`).join("")}</select></div>
    <div><label>Date</label><input id="xD" type="date" value="${e.spent_on}" max="${today()}"></div></div>
    <div class="two"><div><label>Amount (KES)</label><input id="xA" type="number" inputmode="decimal" min="0" value="${e.amount ?? ""}"></div>
    <div><label>M-Pesa charge (KES)</label><input id="xFee" type="number" inputmode="decimal" min="0" value="${e.fee || ""}" placeholder="0"></div></div>
    <label>M-Pesa code (if paid by M-Pesa)</label><input id="xCode" value="${esc(e.mpesa_code || "")}" placeholder="e.g. TJK4XY12AB" style="text-transform:uppercase">
    ${isNew ? `<label>Proof photo (receipt or M-Pesa screenshot)</label><input id="xPh" type="file" accept="image/*">` : ""}
    <div class="sub" style="margin-top:6px">Proof is required for ${KES(THRESHOLD)} and above before the float can be submitted.</div>
    <div class="rowflex" style="margin-top:14px"><button class="btn" id="xSave" onclick="saveExpense(${e.id || 0}, ${e.float_id})">${isNew ? "Save expense" : "Save changes"}</button>
    ${isNew ? "" : `${e.proof ? `<button class="btn ghost" onclick="attachProof(${e.id})">Replace proof</button>` : `<button class="btn ghost" onclick="attachProof(${e.id})">Attach proof</button>`}
      <button class="btn bad" onclick="deleteExpense(${e.id})">Delete</button>`}
    <button class="btn ghost" onclick="closeSheet()">Cancel</button></div>`);
}

const readPaste = run(async () => {
  const p = await post("/api/tools/parse-mpesa", {text: $("xP").value});
  if (p.mpesa_code) $("xCode").value = p.mpesa_code;
  if (p.amount != null) $("xA").value = p.amount;
  if (p.fee != null) $("xFee").value = p.fee;
  if (p.payee && !$("xN").value) $("xN").value = "Paid " + p.payee;
  if (p.date && p.date <= today()) $("xD").value = p.date;
  toast(p.amount != null ? "Message read — check the details" : "Couldn't find an amount in that message", p.amount == null);
});

const saveExpense = run(async (eid, fid) => {
  const btn = $("xSave"); btn.disabled = true;
  try {
    const body = {description: $("xN").value, category: $("xC").value, spent_on: $("xD").value,
                  amount: $("xA").value, fee: $("xFee").value || 0, mpesa_code: $("xCode").value};
    if (eid) { await api("/api/expenses/" + eid, {method: "PATCH", body}); toast("Expense updated"); }
    else {
      const target = $("xF") ? +$("xF").value : fid;
      const e = await post(`/api/floats/${target}/expenses`, body);
      const file = $("xPh").files[0];
      if (file) {
        try {
          const r = await uploadPhoto(`/api/expenses/${e.id}/proof`, file, {kind: body.mpesa_code ? "M-Pesa" : "Receipt"});
          toast(`Saved · photo ${kb(r.before)} → ${kb(r.after)}`);
        } catch (err) { toast("Expense saved, but the photo failed: " + err.message, true); }
      } else toast(e.needs_proof ? "Saved — proof still needed for this amount" : "Expense saved");
      if (target !== fid || !location.hash.startsWith("#float/")) { closeSheet(); return go("float/" + target); }
    }
    route();
  } finally { btn.disabled = false; }
});

const deleteExpense = run(async eid => {
  if (!confirm("Delete this expense? This can't be undone.")) return;
  await api("/api/expenses/" + eid, {method: "DELETE"}); toast("Expense deleted"); route();
});

function attachProof(eid) {
  const e = CUR.expenses.find(x => x.id === eid);
  openSheet(`<h2>Attach proof</h2><div style="font-size:13px;margin-bottom:6px">${esc(e.description)} · ${KES(e.total)}</div>
    <label>Type</label><select id="pk"><option ${e.mpesa_code ? "selected" : ""}>M-Pesa</option><option ${e.mpesa_code ? "" : "selected"}>Receipt</option><option>Photo</option></select>
    <label>Photo or screenshot</label><input type="file" accept="image/*" id="pf">
    <div class="sub" style="margin-top:6px">The photo is shrunk to about 200 KB on your phone before uploading.</div>
    <div class="rowflex" style="margin-top:14px"><button class="btn" id="pGo" onclick="saveProof(${eid})">Attach</button><button class="btn ghost" onclick="closeSheet()">Cancel</button></div>`);
}
const saveProof = run(async eid => {
  const f = $("pf").files[0];
  if (!f) throw new Error("Choose a photo first.");
  $("pGo").disabled = true;
  try {
    const r = await uploadPhoto(`/api/expenses/${eid}/proof`, f, {kind: $("pk").value});
    toast(`Photo saved: ${kb(r.before)} → ${kb(r.after)}`); route();
  } finally { if ($("pGo")) $("pGo").disabled = false; }
});
function showProof(eid) {
  const e = CUR.expenses.find(x => x.id === eid), editable = CUR.manager_id === ME.id && !locked(CUR);
  openSheet(`<h2>${esc(e.description)}</h2><div class="sub" style="margin-bottom:10px">${fmtDate(e.spent_on)} · ${esc(e.category)} · ${KES(e.total)} · ${e.proof.kind} · ${kb(e.proof.size)}</div>
    <img class="full" src="/api/expenses/${e.id}/proof?s=${e.proof.size}" alt="proof">
    <div class="rowflex" style="margin-top:12px">${editable ? `<button class="btn ghost" onclick="attachProof(${e.id})">Replace</button><button class="btn ghost" onclick="removeProof(${e.id})">Remove</button>` : ""}
    <a class="btn ghost" href="/api/expenses/${e.id}/proof" target="_blank" rel="noopener">Open full size</a><button class="btn ghost" onclick="closeSheet()">Close</button></div>`);
}
const removeProof = run(async eid => {
  if (!confirm("Remove this proof photo?")) return;
  await api(`/api/expenses/${eid}/proof`, {method: "DELETE"}); toast("Proof removed"); route();
});

/* ---------------------------------------------------------------- team consolidation (admin & boss) */
async function viewTeam() {
  const d = await api("/api/dashboard"), floats = await api("/api/floats");
  $("main").innerHTML = `<div class="grid">${kpi("Floats issued", KES(d.all.given))}${kpi("Spent", KES(d.all.spent))}
      ${kpi("Team balance", KES(d.all.balance), d.all.balance < 0)}${kpi("Awaiting boss", d.all.awaiting)}</div>
    <div class="card"><h2>Managers – consolidated</h2>
    <table><tr><th>Manager</th><th class="r">Given</th><th class="r">Spent</th><th class="r">Balance</th></tr>
    ${d.managers.map(m => `<tr><td>${esc(m.name)}<br><span class="sub">${m.floats} float(s)${m.awaiting ? ` · ${m.awaiting} awaiting` : ""}${m.queried ? ` · ${m.queried} queried` : ""}</span></td>
      <td class="r">${KES(m.given)}</td><td class="r">${KES(m.spent)}</td><td class="r" style="${m.balance < 0 ? "color:var(--bad)" : ""}">${KES(m.balance)}</td></tr>`).join("")}
    </table></div>
    <div class="card"><h2>All floats</h2><table><tr><th>Float</th><th>Manager</th><th class="r">Balance</th><th class="r">Status</th></tr>
    ${floats.map(f => `<tr class="clickable" onclick="go('float/${f.id}')"><td>${esc(f.label)}<br><span class="sub">${f.code} · ${fmtDate(f.issued_on)}</span></td><td>${esc(f.manager)}</td>
      <td class="r" style="${f.balance < 0 ? "color:var(--bad)" : ""}">${KES(f.balance)}</td><td class="r">${pill(f.status)}</td></tr>`).join("") || `<tr><td colspan="4" class="sub">No floats yet.</td></tr>`}
    </table></div>`;
}

/* ---------------------------------------------------------------- field & office reports */
function reportRow(r) {
  return `<div class="tx clickable" onclick="go('report/${r.id}')"><div class="m"><div class="n">${esc(r.title)}</div>
    <div class="s">${fmtDate(r.report_date)} · ${r.kind} · ${esc(r.author)}${r.decision_needed ? " · decision needed" : ""} · ${r.photo_count} photo(s) · ${r.reply_count} repl${r.reply_count === 1 ? "y" : "ies"}</div></div>${pill(r.status)}</div>`;
}
async function viewReports() {
  const rs = await api("/api/field-reports");
  $("main").innerHTML = `${ME.role !== "boss" ? `<div class="rowflex" style="margin-bottom:12px"><button class="btn" onclick="newReport()">+ Write a report</button></div>` : ""}
    <div class="card"><h2>Field &amp; office reports</h2>${rs.map(reportRow).join("") || `<div class="sub">No reports yet.</div>`}</div>`;
}
function newReport() {
  openSheet(`<h2>Write a report</h2>
    <div class="two"><div><label>Type</label><select id="rK"><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="one-off">One-off</option></select></div>
    <div><label>Date</label><input id="rD" type="date" value="${today()}" max="${today()}"></div></div>
    <label>Title</label><input id="rT" placeholder="e.g. Kayole KP machine down">
    <label>What happened</label><textarea id="rB" rows="6"></textarea>
    <label>Decision needed from the boss (optional)</label><textarea id="rN" rows="2" placeholder="e.g. Approve KES 6,000 for the pump repair?"></textarea>
    <label>Photos (optional)</label><input id="rP" type="file" accept="image/*" multiple>
    <div class="rowflex" style="margin-top:14px"><button class="btn" id="rGo" onclick="sendReport()">Send to boss</button><button class="btn ghost" onclick="closeSheet()">Cancel</button></div>`);
}
const sendReport = run(async () => {
  $("rGo").disabled = true;
  try {
    const r = await post("/api/field-reports", {kind: $("rK").value, report_date: $("rD").value, title: $("rT").value,
                                                body: $("rB").value, decision_needed: $("rN").value});
    let failed = 0;
    for (const f of $("rP").files) { try { await uploadPhoto(`/api/field-reports/${r.id}/photos`, f); } catch (e) { failed++; } }
    toast(failed ? `Report sent, but ${failed} photo(s) failed` : "Report sent", !!failed);
    go("report/" + r.id);
  } finally { if ($("rGo")) $("rGo").disabled = false; }
});
let CUR_R = null;
async function viewReport(id) {
  const r = CUR_R = await api("/api/field-reports/" + id);
  const mine = r.author_id === ME.id, canDecide = (ME.role === "boss" || ME.role === "admin") && !mine;
  $("main").innerHTML = `<div class="card"><div class="spread"><div><h2 style="margin:0">${esc(r.title)}</h2>
      <div class="sub">${r.kind} report · ${fmtDate(r.report_date)} · ${esc(r.author)}</div></div>${pill(r.status)}</div>
    <div style="white-space:pre-wrap;margin-top:12px">${esc(r.body) || `<span class="sub">No details written.</span>`}</div>
    ${r.decision_needed ? `<div class="note info"><b>Decision needed:</b> ${esc(r.decision_needed)}</div>` : ""}
    ${r.photos.length ? `<h3>Photos</h3><div class="photos">${r.photos.map(p => `<img loading="lazy" src="/api/field-reports/${r.id}/photos/${p.id}" alt="${esc(p.caption)}" onclick="showPhoto(${p.id})">`).join("")}</div>` : ""}
    <div class="rowflex" style="margin-top:12px">
      ${canDecide ? `<button class="btn ok" onclick="decideReport('APPROVED')">Approve</button><button class="btn bad" onclick="decideReport('DECLINED')">Decline</button><button class="btn ghost" onclick="decideReport('NOTED')">Mark as noted</button>` : ""}
      ${mine ? `<label class="btn ghost" style="margin:0;color:var(--brand)">+ Add photo<input type="file" accept="image/*" class="hide" onchange="addReportPhoto(this)"></label>` : ""}
      <a class="btn ghost" href="/api/field-reports/${r.id}/report.pdf" target="_blank" rel="noopener">PDF</a></div></div>
    <div class="card"><h2>Replies</h2>${r.replies.map(x => `<div class="reply"><b>${esc(x.author)}</b> <span class="sub">${fmtTime(x.at)}</span><div style="white-space:pre-wrap">${esc(x.body)}</div></div>`).join("") || `<div class="sub">No replies yet.</div>`}
      <label>Write a reply</label><textarea id="rep" rows="3"></textarea>
      <div class="rowflex" style="margin-top:8px"><button class="btn" onclick="sendReply()">Send reply</button></div></div>`;
}
function showPhoto(pid) {
  const p = CUR_R.photos.find(x => x.id === pid);
  openSheet(`<img class="full" src="/api/field-reports/${CUR_R.id}/photos/${pid}" alt=""><div class="sub" style="margin-top:6px">${esc(p.caption)}</div>
    <div style="margin-top:10px"><button class="btn ghost" onclick="closeSheet()">Close</button></div>`);
}
const addReportPhoto = run(async input => {
  if (!input.files[0]) return;
  await uploadPhoto(`/api/field-reports/${CUR_R.id}/photos`, input.files[0]); toast("Photo added"); route();
});
const sendReply = run(async () => { await post(`/api/field-reports/${CUR_R.id}/replies`, {body: $("rep").value}); toast("Reply sent"); route(); });
function decideReport(status) {
  openSheet(`<h2>${{APPROVED: "Approve", DECLINED: "Decline", NOTED: "Mark as noted"}[status]}</h2>
    <label>Comment (optional)</label><textarea id="dc" rows="3"></textarea>
    <div class="rowflex" style="margin-top:12px"><button class="btn" onclick="doDecide('${status}')">Confirm</button><button class="btn ghost" onclick="closeSheet()">Cancel</button></div>`);
}
const doDecide = run(async status => { await post(`/api/field-reports/${CUR_R.id}/decision`, {status, comment: $("dc").value}); toast("Saved"); route(); });

/* ---------------------------------------------------------------- people (admin) */
async function viewPeople() {
  const us = await api("/api/users");
  $("main").innerHTML = `<div class="rowflex" style="margin-bottom:12px"><button class="btn" onclick="userSheet()">+ Add person</button></div>
    <div class="card"><h2>People</h2><table><tr><th>Name</th><th>Phone</th><th>Role</th><th></th></tr>
    ${us.map(u => `<tr><td>${esc(u.full_name)}${u.is_active ? "" : ' <span class="pill p-bad">INACTIVE</span>'}</td><td>${esc(u.phone)}</td><td>${u.role}</td>
      <td class="r"><button class="btn ghost small" onclick="userSheet(${u.id})">Edit</button></td></tr>`).join("")}</table>
    <div class="sub" style="margin-top:8px"><b>Manager</b>: records own floats and expenses, sees only their own. <b>Boss</b>: sees everyone, approves or queries, can't change figures. <b>Admin</b>: manages people and settings, holds floats too.</div></div>`;
  window._users = us;
}
function userSheet(uid) {
  const u = uid ? window._users.find(x => x.id === uid) : {role: "manager", is_active: true};
  openSheet(`<h2>${uid ? "Edit " + esc(u.full_name) : "Add person"}</h2>
    <label>Full name</label><input id="uN" value="${esc(u.full_name || "")}">
    ${uid ? "" : `<label>Phone number</label><input id="uP" inputmode="tel" placeholder="0712345678">`}
    <label>Role</label><select id="uR">${["manager", "boss", "admin"].map(r => `<option ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}</select>
    <label>${uid ? "New password (leave blank to keep)" : "Password (at least 8 characters)"}</label><input id="uW" type="text" autocomplete="off">
    ${uid ? `<label style="display:flex;gap:8px;align-items:center;color:var(--ink)"><input type="checkbox" id="uA" style="width:auto" ${u.is_active ? "checked" : ""}> Active (can sign in)</label>` : ""}
    <div class="rowflex" style="margin-top:14px"><button class="btn" onclick="saveUser(${uid || 0})">Save</button><button class="btn ghost" onclick="closeSheet()">Cancel</button></div>`);
}
const saveUser = run(async uid => {
  if (uid) {
    const body = {full_name: $("uN").value, role: $("uR").value, is_active: $("uA").checked};
    if ($("uW").value) body.password = $("uW").value;
    await api("/api/users/" + uid, {method: "PATCH", body});
  } else await post("/api/users", {full_name: $("uN").value, phone: $("uP").value, role: $("uR").value, password: $("uW").value});
  toast("Saved"); route();
});

/* ---------------------------------------------------------------- settings */
async function viewSettings() {
  const isAdmin = ME.role === "admin";
  $("main").innerHTML = `<div class="card"><h2>Proof rule</h2>
      <div class="sub">Expenses at or above this amount (including the M-Pesa charge) need a receipt or M-Pesa photo before a float can be submitted.</div>
      ${isAdmin ? `<label>Proof required from (KES)</label><input type="number" id="th" value="${THRESHOLD}" inputmode="numeric">
      <div class="rowflex" style="margin-top:10px"><button class="btn" onclick="saveThreshold()">Save rule</button></div>` : `<div class="note info">Currently ${KES(THRESHOLD)} and above.</div>`}</div>
    <div class="card"><h2>Duplicate M-Pesa codes</h2><div class="sub">Each M-Pesa code can be claimed only once in the whole system. A second use is blocked when saving.</div></div>
    <div class="card"><h2>Photos</h2><div class="sub">Photos are shrunk on the phone to about 200 KB before upload, so receipts stay readable and the database stays small.</div></div>
    <div class="card"><h2>My account</h2><div class="sub">${esc(ME.full_name)} · ${esc(ME.phone)} · ${ME.role}</div>
      <div class="rowflex" style="margin-top:10px"><button class="btn ghost" onclick="$('who').click()">Change password / sign out</button></div></div>
    ${isAdmin ? `<div class="card"><h2>Activity log</h2><div id="aud" class="sub">Loading…</div></div>` : ""}`;
  if (isAdmin) {
    const rows = await api("/api/audit?limit=100");
    $("aud").innerHTML = `<table>${rows.map(a => `<tr><td style="white-space:nowrap">${fmtTime(a.at)}</td><td>${esc(a.who)}</td><td><b>${a.action.replace(/_/g, " ")}</b> ${esc(a.detail)}</td></tr>`).join("")}</table>`;
  }
}
const saveThreshold = run(async () => {
  const s = await api("/api/settings", {method: "PUT", body: {proof_threshold: $("th").value}});
  THRESHOLD = s.proof_threshold; toast("Proof rule updated");
});

boot();
