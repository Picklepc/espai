/* ESPAI Hub — Main app
   Handles navigation, data loading, and rendering for all views. */

// ── Design token injection ─────────────────────────────────────────────────

async function loadTokens() {
  try {
    const tokens = await api.design.tokens();
    const root = document.documentElement.style;
    for (const [key, value] of Object.entries(tokens)) {
      // "color.background" → "--color-background"
      const prop = "--" + key.replace(/\./g, "-");
      root.setProperty(prop, value);
    }
  } catch (_) {
    // tokens unavailable — CSS fallbacks apply
  }
}

// ── Hub status ─────────────────────────────────────────────────────────────

const statusEl = document.getElementById("hubStatus");

async function checkHubStatus() {
  try {
    await api.status();
    statusEl.textContent = "● Hub online";
    statusEl.className = "hub-status online";
  } catch (_) {
    statusEl.textContent = "● Hub offline";
    statusEl.className = "hub-status offline";
  }
}

// ── Navigation ─────────────────────────────────────────────────────────────

const navItems = document.querySelectorAll(".nav-item");
const views    = document.querySelectorAll(".view");

function showView(name) {
  views.forEach(v => v.classList.toggle("active", v.id === `view-${name}`));
  navItems.forEach(n => n.classList.toggle("active", n.dataset.view === name));
  // Reset project detail when navigating away
  if (name !== "projects") {
    _currentProject = null;
    _stopFilesPoller();
    document.getElementById("proj-detail-view")?.classList.add("hidden");
    document.getElementById("proj-list-view")?.classList.remove("hidden");
  }
  if (name !== "agent-bench") {
    _stopAbPoller();
  }
  loadView(name);
}

navItems.forEach(item => {
  item.addEventListener("click", e => {
    e.preventDefault();
    showView(item.dataset.view);
  });
});

// ── Helpers ────────────────────────────────────────────────────────────────

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html) e.innerHTML = html;
  return e;
}

function timeAgo(isoStr) {
  if (!isoStr) return "—";
  const diff = Date.now() - new Date(isoStr).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function isOnline(lastSeen) {
  if (!lastSeen) return false;
  return (Date.now() - new Date(lastSeen).getTime()) < 120_000; // 2 min
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

// ── Global tooltip (data-tip="…") ─────────────────────────────────────────
// Convention: every interactive element must have data-tip="one sentence".
// Simple one-liners use this system. Complex structured info (Doctor rows)
// uses the separate _showDoctorTooltip / _hideDoctorTooltip system.

const _appTip    = document.getElementById("appTip");
let   _tipTimer  = null;
let   _tipTarget = null;

function _positionAppTip(el) {
  const rect   = el.getBoundingClientRect();
  const margin = 8;
  _appTip.style.left = "0"; _appTip.style.top = "0"; // reset before measuring
  _appTip.classList.remove("hidden");
  const tw = _appTip.offsetWidth;
  const th = _appTip.offsetHeight;
  let left = rect.left + rect.width / 2 - tw / 2;   // centered below
  let top  = rect.bottom + margin;
  if (top + th > window.innerHeight - margin) top = rect.top - th - margin; // flip up
  _appTip.style.left = Math.max(margin, Math.min(left, window.innerWidth - tw - margin)) + "px";
  _appTip.style.top  = Math.max(margin, top) + "px";
}

function _showAppTip(el) {
  const text = el.dataset.tip;
  if (!text) return;
  _appTip.textContent = text;
  _tipTarget = el;
  clearTimeout(_tipTimer);
  _tipTimer = setTimeout(() => _positionAppTip(el), 400); // 400 ms delay
}

function _hideAppTip() {
  clearTimeout(_tipTimer);
  _appTip.classList.add("hidden");
  _tipTarget = null;
}

// Wire once at document level — catches dynamically added [data-tip] elements too
document.addEventListener("mouseover", e => {
  const el = e.target.closest("[data-tip]");
  if (el && el !== _tipTarget) _showAppTip(el);
}, true);

document.addEventListener("mouseout", e => {
  const el = e.target.closest("[data-tip]");
  if (el) _hideAppTip();
}, true);

// Hide on scroll or any click
document.addEventListener("scroll", _hideAppTip, true);
document.addEventListener("click",  _hideAppTip, true);

// ── Unified agent task modal (context-aware) ───────────────────────────────
// Call with no args for the full form (from Agent Bench tab).
// Pass ctx to pre-scope the task to a project or worker.
async function _openAgentTaskModal(ctx = {}) {
  const { context_type, context_id, context_label, parent_task_id } = ctx;
  const hasContext = !!(context_type && context_id);

  // Load project options only when no context (full form)
  let projOptsHTML = '<option value="">— no project —</option>';
  if (!hasContext) {
    let projects = [];
    try { projects = await api.projects.list(); } catch (_) {}
    projOptsHTML = ['<option value="">— no project —</option>',
      ...projects.map(p => `<option value="${p.id}">${p.name}</option>`)].join("");
  }

  const contextBanner = hasContext ? `
    <div style="display:flex;align-items:center;gap:10px;padding:9px 12px;
                background:var(--color-card);border:1px solid var(--color-card-border);
                border-left:3px solid var(--color-accent);border-radius:6px;margin-bottom:14px;font-size:12px">
      <span style="color:var(--color-text-muted)">Scoped to</span>
      <strong>${context_type === "project" ? "🗂 Project" : "⚙ Worker"}: ${context_label || context_id}</strong>
      <span style="color:var(--color-text-muted);margin-left:auto;opacity:.75">Paths &amp; criteria auto-inferred from template</span>
    </div>` : `
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:14px;line-height:1.6">
      Describe what you want to build. The agent reads the relevant code, makes changes,
      and submits a diff for your review. Pick the closest template so it focuses on the right files.
    </p>`;

  const threadNote = parent_task_id ? `
    <div style="font-size:12px;color:var(--color-warning);padding:6px 10px;background:rgba(240,168,32,.08);
                border-radius:6px;margin-bottom:12px">
      ↩ Follow-up task — include what needs to change from the previous run.
    </div>` : "";

  openModal(parent_task_id ? "Follow-up Task" : "New Agent Task", `
    ${threadNote}${contextBanner}
    <div class="form-field">
      <label data-tip="Short label shown in the task list">Title</label>
      <input type="text" id="abNewTitle" placeholder="${parent_task_id ? "e.g. Fix the issue flagged in the previous run" : "e.g. Add PIR motion sensor on GPIO 14"}">
    </div>
    <div class="form-field">
      <label data-tip="Be specific — pin numbers, event types, API names, file names help the agent target the right code">Description</label>
      <textarea id="abNewDesc" rows="${hasContext ? 4 : 5}" placeholder="${_templatePlaceholders["firmware-feature"]}"></textarea>
    </div>
    <div class="form-field">
      <label data-tip="Tells the agent which codebase area to focus on">Template</label>
      <select id="abNewTemplate">
        <option value="firmware-feature">firmware-feature — ESP32 code</option>
        <option value="hub-feature">hub-feature — hub backend or API</option>
        <option value="port-to-hub">port-to-hub — mirror device to hub + ESP32 fallback</option>
        <option value="recipe-feature">recipe-feature — YAML data pipeline</option>
        <option value="bug-fix">bug-fix — diagnose and fix</option>
        <option value="custom">custom — no constraints</option>
      </select>
    </div>
    ${!hasContext ? `
    <div class="form-field">
      <label data-tip="Link to a project so the agent uses its description as context">Project</label>
      <select id="abNewProject">${projOptsHTML}</select>
    </div>` : ""}
    <details style="margin-top:10px">
      <summary style="font-size:12px;color:var(--color-text-muted);cursor:pointer;user-select:none;padding:4px 0"
               data-tip="Override the inferred criteria or paths if you need finer control">
        Advanced — override inferred criteria &amp; paths
      </summary>
      <div style="margin-top:10px">
        <div class="form-field">
          <label data-tip="Leave blank to auto-infer from template. One per line starting with -">Acceptance Criteria</label>
          <textarea id="abNewCriteria" rows="3" placeholder="- Leave blank to auto-infer from template&#10;- e.g. Firmware compiles without errors"></textarea>
        </div>
        ${!hasContext ? `
        <div class="form-field">
          <label data-tip="Leave blank — paths are inferred from the project context and template. Seed and provision firmware are always protected and cannot be listed here.">Allowed Paths (one per line)</label>
          <textarea id="abNewPaths" rows="2" placeholder="Leave blank — inferred from project context. e.g. projects/abc123/firmware/"></textarea>
        </div>` : ""}
      </div>
    </details>
  `, [
    { label: "Create Task", cls: "btn btn-primary", action: async () => {
      const title       = document.getElementById("abNewTitle").value.trim();
      const desc        = document.getElementById("abNewDesc").value.trim();
      if (!title || !desc) return;
      const template    = document.getElementById("abNewTemplate").value;
      const project_id  = hasContext ? null : (document.getElementById("abNewProject")?.value || null);
      const criteriaRaw = document.getElementById("abNewCriteria")?.value?.trim() || "";
      const pathsRaw    = !hasContext ? (document.getElementById("abNewPaths")?.value?.trim() || "") : "";
      const acceptance_criteria = criteriaRaw ? criteriaRaw.split("\n").map(s => s.trim().replace(/^[-*]\s*/, "")).filter(Boolean) : [];
      const allowed_paths       = pathsRaw ? pathsRaw.split("\n").map(s => s.trim()).filter(Boolean) : [];
      try {
        await api.agentBench.createTask({
          title, description: desc, template,
          ...(project_id    ? { project_id }    : {}),
          ...(hasContext     ? { context_type, context_id } : {}),
          ...(parent_task_id ? { parent_task_id } : {}),
          ...(acceptance_criteria.length ? { acceptance_criteria } : {}),
          ...(allowed_paths.length       ? { allowed_paths }       : {}),
        });
        closeModal();
        _abLoadTaskList();
        if (context_type === "project" && context_id) _loadProjectTasks(context_id);
      } catch (err) { alert("Error: " + err.message); }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);

  // Live placeholder update on template change
  const sel = document.getElementById("abNewTemplate");
  const ta  = document.getElementById("abNewDesc");
  if (sel && ta) {
    const upd = () => { ta.placeholder = _templatePlaceholders[sel.value] || _templatePlaceholders["custom"]; };
    sel.addEventListener("change", upd);
    upd();
  }
}

// ── Project task list ──────────────────────────────────────────────────────

async function _loadProjectTasks(projectId) {
  const listEl = document.getElementById("projTaskList");
  if (!listEl) return;
  listEl.innerHTML = '<div class="empty-state" style="font-size:12px">Loading…</div>';

  let tasks = [];
  try {
    // Fetch tasks scoped to this project (context OR project_id)
    const [ctx, legacy] = await Promise.all([
      api.agentBench.listTasks({ context_type: "project", context_id: projectId }).catch(() => []),
      api.agentBench.listTasks({ project_id: projectId }).catch(() => []),
    ]);
    const seen = new Set();
    for (const t of [...ctx, ...legacy]) { if (!seen.has(t.id)) { tasks.push(t); seen.add(t.id); } }
  } catch (_) {
    listEl.innerHTML = '<div class="empty-state" style="font-size:12px">Agent Bench is disabled.</div>';
    return;
  }

  if (!tasks.length) {
    listEl.innerHTML = '<div class="empty-state" style="font-size:12px">No agent tasks yet — click <strong>+ Agent Task</strong> to create one scoped to this project.</div>';
    return;
  }

  // Separate root tasks from follow-ups, group children by parent
  const rootTasks = tasks.filter(t => !t.parent_task_id);
  const childMap  = {};
  for (const t of tasks) {
    if (t.parent_task_id) (childMap[t.parent_task_id] ||= []).push(t);
  }

  listEl.innerHTML = "";
  for (const t of rootTasks) {
    const children = childMap[t.id] || [];
    const row = el("div", "proj-task-row");
    const tpl = _AB_TEMPLATE_LABELS[t.template] || t.template;
    row.innerHTML = `
      <span class="${_abStatusClass(t.status)}" data-tip="Status: ${t.status}">${_abStatusLabel(t.status)}</span>
      <span class="proj-task-title" data-tip="Click to open in Agent Bench">${t.title}</span>
      <span class="proj-task-meta">${tpl} · ${timeAgo(t.updated)}</span>
      ${children.length ? `<span class="proj-task-count" data-tip="${children.length} follow-up(s) in thread">+${children.length}</span>` : ""}
    `;
    const followBtn = el("button", "btn btn-secondary btn-sm proj-task-followup", "+ Follow-up");
    followBtn.dataset.tip = "Create a follow-up task in this thread";
    followBtn.onclick = (e) => {
      e.stopPropagation();
      _openAgentTaskModal({ context_type: "project", context_id: projectId, context_label: _currentProject?.name, parent_task_id: t.id });
    };
    row.appendChild(followBtn);
    row.onclick = (e) => {
      if (e.target === followBtn || followBtn.contains(e.target)) return;
      showView("agent-bench");
      // Slight delay so Agent Bench view finishes loading before we open the task
      setTimeout(() => _abOpenTask(t.id), 200);
    };
    listEl.appendChild(row);
  }
}

// ── Fleet view ─────────────────────────────────────────────────────────────

async function loadFleet() {
  const [devices, jobs] = await Promise.all([
    api.devices.list().catch(() => []),
    api.jobs.list("running").catch(() => []),
  ]);

  const online = devices.filter(d => isOnline(d.last_seen));
  const paired = devices.filter(d => d.paired);

  document.getElementById("statTotal").textContent  = devices.length;
  document.getElementById("statOnline").textContent = online.length;
  document.getElementById("statPaired").textContent = paired.length;
  document.getElementById("statJobs").textContent   = jobs.length;

  const listEl = document.getElementById("deviceList");
  if (!devices.length) {
    listEl.innerHTML = '<div class="empty-state">No devices found. Scan LAN or add a device manually.</div>';
    return;
  }

  listEl.innerHTML = "";
  for (const d of devices) {
    const online_ = isOnline(d.last_seen);
    const card = el("div", "device-card");
    const dotClass = online_ ? "device-dot online" : (d.paired ? "device-dot paired" : "device-dot");
    const dotTip   = online_ ? "Online — seen within 2 minutes" : (d.paired ? "Offline — paired but not recently seen" : "Unregistered — not yet paired");
    card.innerHTML = `
      <span class="${dotClass}" data-tip="${dotTip}"></span>
      <div class="device-info">
        <div class="device-name">${d.name || d.id}</div>
        <div class="device-meta">${d.ip || "no IP"} · ${d.board || "unknown board"} · fw ${d.fw_version || "?"} · ${timeAgo(d.last_seen)}</div>
      </div>
      <span class="device-badge ${d.paired ? "" : "unpaired"}" data-tip="${d.paired ? "Paired — trusted for OTA and commands" : "Not paired — click Pair to register this device"}">${d.paired ? "Paired" : "Unpaired"}</span>
    `;
    const actions = el("div", "device-actions");
    if (!d.paired) {
      const pairBtn = el("button", "btn btn-secondary btn-sm");
      pairBtn.textContent = "Pair";
      pairBtn.dataset.tip = "Pair this device with the hub to enable OTA and trusted commands";
      pairBtn.onclick = () => pairDevice(d.id);
      actions.appendChild(pairBtn);
    }
    const delBtn = el("button", "btn btn-danger btn-sm");
    delBtn.innerHTML = "&#x2715;";
    delBtn.dataset.tip = "Remove this device from the fleet";
    delBtn.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`Remove "${d.name || d.id}" from fleet?`)) return;
      await api.devices.delete(d.id).catch(() => {});
      loadFleet();
    };
    actions.appendChild(delBtn);
    card.appendChild(actions);
    listEl.appendChild(card);
  }
}

async function pairDevice(deviceId) {
  // Look up device details for IP / portal link
  let deviceIp = null;
  try {
    const devs = await api.devices.list();
    const dev  = devs.find(d => d.id === deviceId);
    deviceIp   = dev?.ip || null;
  } catch (_) {}

  let pairing;
  try {
    pairing = await api.devices.initiatePair(deviceId);
  } catch (err) {
    alert("Could not initiate pairing: " + err.message);
    return;
  }

  const portalLine = deviceIp
    ? `<a href="http://${deviceIp}" target="_blank" class="btn btn-secondary btn-sm" style="margin-top:6px;display:inline-block">Open Device Portal ↗</a>`
    : `<p style="font-size:12px;color:var(--color-text-muted);margin-top:6px">No IP known — connect to device AP at <b>192.168.4.1</b></p>`;

  const expiresAt = new Date(pairing.expires).toLocaleTimeString();

  openModal("Pair Device", `
    <p style="margin-bottom:14px;color:var(--color-text-muted);font-size:13px">
      Enter this token in your device's Hub configuration panel, or confirm it manually below.
    </p>
    <div id="pairTokenBox" style="font-size:26px;font-family:monospace;letter-spacing:4px;text-align:center;
         padding:18px 12px;background:var(--color-card);border:1px solid var(--color-card-border);
         border-radius:8px;cursor:pointer;position:relative" title="Click to copy">
      ${pairing.token}
      <span style="position:absolute;top:6px;right:8px;font-size:10px;opacity:0.5">CLICK TO COPY</span>
    </div>
    <p style="font-size:11px;color:var(--color-text-muted);text-align:center;margin:4px 0 10px">
      Expires at ${expiresAt}
    </p>
    ${portalLine}
    <hr style="border:none;border-top:1px solid var(--color-card-border);margin:14px 0">
    <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:6px">Or confirm manually:</p>
    <div class="form-field" style="margin-bottom:0">
      <input type="text" id="pairTokenInput" value="${pairing.token}" placeholder="token">
    </div>
    <p id="pairStatus" style="font-size:12px;color:var(--color-accent);margin-top:8px;min-height:16px"></p>
  `, [
    { label: "Confirm Pairing", cls: "btn btn-primary", action: async () => {
      const t = document.getElementById("pairTokenInput")?.value?.trim();
      if (!t) return;
      try {
        await api.devices.confirmPair({ token: t, device_id: deviceId });
        _stopPairPoller();
        closeModal();
        loadFleet();
      } catch (err) {
        const s = document.getElementById("pairStatus");
        if (s) s.textContent = "Error: " + err.message;
      }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: () => { _stopPairPoller(); closeModal(); } },
  ]);

  // Copy-to-clipboard on token box click
  document.getElementById("pairTokenBox")?.addEventListener("click", () => {
    navigator.clipboard?.writeText(pairing.token).then(() => {
      const box = document.getElementById("pairTokenBox");
      if (box) { box.style.outline = "2px solid var(--color-accent)"; setTimeout(() => box.style.outline = "", 800); }
    }).catch(() => {});
  });

  // Auto-poll hub to detect when device confirms pairing on its own
  _startPairPoller(deviceId);
}

let _pairPollTimer = null;

function _startPairPoller(deviceId) {
  _stopPairPoller();
  _pairPollTimer = setInterval(async () => {
    try {
      const devs = await api.devices.list();
      const dev  = devs.find(d => d.id === deviceId);
      if (dev?.paired) {
        _stopPairPoller();
        const s = document.getElementById("pairStatus");
        if (s) s.textContent = "Device confirmed pairing!";
        setTimeout(() => { closeModal(); loadFleet(); }, 1200);
      } else {
        const s = document.getElementById("pairStatus");
        if (s && !s.textContent.startsWith("Error")) s.textContent = "Waiting for device confirmation…";
      }
    } catch (_) {}
  }, 2500);
}

function _stopPairPoller() {
  if (_pairPollTimer) { clearInterval(_pairPollTimer); _pairPollTimer = null; }
}

// ── Add Device modal ───────────────────────────────────────────────────────

document.getElementById("btnAddDevice").onclick = () => {
  openModal("Add Device Manually", `
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:14px;line-height:1.6">
      Use this when your device doesn't respond to LAN scan — for example if it's on a
      different subnet, has a static IP, or is connected via a serial-to-network bridge.
    </p>
    <div class="form-field">
      <label data-tip="The device's current IP address on your local network — check your router's DHCP table or the device's serial output">IP Address</label>
      <input type="text" id="newDeviceIP" placeholder="e.g. 192.168.1.45">
    </div>
    <div class="form-field">
      <label data-tip="A human-readable name shown in Fleet, events, and rules — use something descriptive like the room or sensor type">Name (optional)</label>
      <input type="text" id="newDeviceName" placeholder="e.g. kitchen-sensor">
    </div>
  `, [
    { label: "Add", cls: "btn btn-primary", action: async () => {
      const ip   = document.getElementById("newDeviceIP").value.trim();
      const name = document.getElementById("newDeviceName").value.trim();
      if (!ip) return;
      await api.devices.addManual({ ip, name: name || null });
      closeModal();
      loadFleet();
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
};

document.getElementById("btnScan").onclick = async () => {
  openModal("Scanning LAN…", `
    <div style="text-align:center;padding:24px 0">
      <div style="font-size:32px;margin-bottom:12px">📡</div>
      <p style="color:var(--color-text-muted)">Probing 254 addresses on local subnet…</p>
    </div>
  `, []);
  try {
    const result = await api.devices.scan();
    if (!result.found) {
      closeModal();
      openModal("Scan Complete", `
        <div class="empty-state">No ESPAI nodes found on <code>${result.subnet}.x</code>.</div>
      `, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    } else {
      const rows = result.devices.map(d => `
        <div class="device-card" style="margin-bottom:6px">
          <span class="device-dot online"></span>
          <div class="device-info">
            <div class="device-name">${d.name || d.id || "Unknown"}</div>
            <div class="device-meta">${d.ip} · ${d.board || "?"} · fw ${d.fw_version || "?"}</div>
          </div>
        </div>
      `).join("");
      closeModal();
      openModal(`Found ${result.found} node${result.found !== 1 ? "s" : ""}`, `
        <p style="margin-bottom:14px;color:var(--color-text-muted);font-size:13px">
          Scanned <code>${result.subnet}.x</code> — registered to fleet automatically.
        </p>
        ${rows}
      `, [{ label: "Done", cls: "btn btn-primary", action: () => { closeModal(); loadFleet(); } }]);
    }
  } catch (err) {
    closeModal();
    openModal("Scan Failed", `<p class="empty-state">${err.message}</p>`,
      [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
  }
};

// ── Backup / Restore ───────────────────────────────────────────────────────

document.getElementById("btnBackupDownload").onclick = () => api.admin.download();

document.getElementById("btnRestoreBackup").onclick = () => {
  openModal("Restore from Backup", `
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:12px;line-height:1.6">
      Paste the JSON from a previous backup download. Only <strong>devices</strong>,
      <strong>projects</strong>, and <strong>rules</strong> are restored — events, jobs,
      and OTA history are never overwritten. Existing records with matching IDs are updated.
    </p>
    <div class="form-field">
      <label style="font-size:12px" data-tip="Paste the full JSON from a hub backup download — the file you get when clicking the Backup button">Backup JSON</label>
      <textarea id="restoreJson" rows="9" style="font-family:monospace;font-size:11px" placeholder='{"devices":[...],"projects":[...],"rules":[...]}'></textarea>
    </div>
    <p id="restoreStatus" style="font-size:12px;min-height:14px;margin-top:6px"></p>
  `, [
    { label: "Restore", cls: "btn btn-primary", action: async () => {
      const raw = document.getElementById("restoreJson")?.value?.trim();
      if (!raw) return;
      let body;
      try { body = JSON.parse(raw); } catch (_) {
        const s = document.getElementById("restoreStatus"); if (s) s.textContent = "Invalid JSON"; return;
      }
      try {
        const result = await api.admin.restore(body);
        const counts = Object.entries(result.restored || {}).map(([t, n]) => `${t}: ${n}`).join(", ");
        closeModal();
        alert(`Restore complete — ${counts}`);
      } catch (err) {
        const s = document.getElementById("restoreStatus"); if (s) s.textContent = "Error: " + err.message;
      }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
};

// ── OTA upload modal ───────────────────────────────────────────────────────

document.getElementById("btnUploadFirmware").onclick = () => {
  openModal("Upload Firmware Binary", `
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:14px;line-height:1.6">
      Upload a compiled <code>.bin</code> from PlatformIO, Arduino IDE, or ESP-IDF.
      In PlatformIO the file is typically at <code>.pio/build/&lt;env&gt;/firmware.bin</code>.
      After upload, use <strong>Push to Device</strong> to deploy it to a paired ESP32.
    </p>
    <div class="form-field">
      <label data-tip="The compiled firmware binary — .bin format only. Found in .pio/build/&lt;env&gt;/firmware.bin after a PlatformIO build.">Firmware .bin file</label>
      <input type="file" id="fwFile" accept=".bin">
    </div>
    <div class="form-field">
      <label data-tip="Must match your PlatformIO environment name or IDF target exactly (e.g. esp32dev, lolin32, esp32-s3-devkitc-1). A board mismatch is flagged as a warning when pushing.">Board</label>
      <input type="text" id="fwBoard" placeholder="esp32dev" value="esp32dev">
    </div>
    <div class="form-field">
      <label data-tip="Semantic version — increment with every build so devices can determine whether an update is available (e.g. 1.0.0, 1.1.0, 2.0.0).">Version</label>
      <input type="text" id="fwVersion" placeholder="1.0.0" value="1.0.0">
    </div>
    <div class="form-field">
      <label data-tip="Release stage: dev for active development builds, beta for limited rollout testing, stable for production devices. Devices can be configured to follow a specific channel.">Channel</label>
      <select id="fwChannel">
        <option value="dev">dev — active development, may be unstable</option>
        <option value="beta">beta — ready for limited testing</option>
        <option value="stable">stable — production-ready release</option>
      </select>
    </div>
  `, [
    { label: "Upload", cls: "btn btn-primary", action: async () => {
      const file    = document.getElementById("fwFile").files[0];
      const board   = document.getElementById("fwBoard").value.trim();
      const version = document.getElementById("fwVersion").value.trim();
      const channel = document.getElementById("fwChannel").value;
      if (!file) { alert("Select a .bin file."); return; }
      if (!board || !version) { alert("Board and version are required."); return; }
      try {
        await api.ota.upload(file, board, version, channel);
        closeModal();
        loadOTA();
      } catch (err) {
        alert("Upload failed: " + err.message);
      }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
};

// ── Projects view ──────────────────────────────────────────────────────────

async function loadProjects() {
  const projects = await api.projects.list().catch(() => []);
  const listEl = document.getElementById("projectList");
  if (!projects.length) {
    listEl.innerHTML = '<div class="empty-state">No projects yet.</div>';
    return;
  }
  listEl.innerHTML = "";
  for (const p of projects) {
    const card = el("div", "reg-card");
    card.style.cursor = "pointer";
    const devCount = Array.isArray(p.devices) ? p.devices.length : 0;
    card.innerHTML = `
      <div class="reg-card-title">${p.name}</div>
      <div class="reg-card-sub">${p.description || ""}</div>
      <div class="tag-row">
        <span class="tag">${devCount} device${devCount !== 1 ? "s" : ""}</span>
        <span class="tag">${timeAgo(p.created)}</span>
      </div>
    `;
    card.onclick = () => openProject(p);
    listEl.appendChild(card);
  }
}

// ── Project detail view ────────────────────────────────────────────────────

let _currentProject       = null;
let _filesPollTimer       = null;
let _filesSnapshot        = "";
let _projectThemeVars     = [];   // CSS var names applied by current project

function _applyProjectTheme(tokens) {
  _clearProjectTheme();
  const root = document.documentElement;
  for (const [k, v] of Object.entries(tokens || {})) {
    root.style.setProperty(k, v);
    _projectThemeVars.push(k);
  }
}

function _clearProjectTheme() {
  const root = document.documentElement;
  for (const k of _projectThemeVars) root.style.removeProperty(k);
  _projectThemeVars = [];
}

function _pathToVSCodeUri(rootPath) {
  const fwd = (rootPath || "").replace(/\\/g, "/");
  return encodeURI("vscode://file/" + fwd);
}

async function refreshProjectFiles(projectId, silent = false) {
  const fileList  = document.getElementById("projFileList");
  const statusEl  = document.getElementById("projFilesStatus");
  if (!silent) fileList.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const { files, root } = await api.projects.files(projectId);

    // Wire VS Code button when we have a root path
    const vsBtn = document.getElementById("btnOpenVSCode");
    if (vsBtn && root) {
      const fwDir = root.replace(/\\/g, "/") + "/firmware";
      vsBtn.style.display = "";
      vsBtn.dataset.tip   = `Open ${fwDir} in VS Code`;
      vsBtn.onclick       = () => window.open(_pathToVSCodeUri(fwDir), "_self");
    }
    const snapshot = JSON.stringify(files.map(f => f.path + f.size_bytes));

    // Avoid re-rendering if nothing changed (silent poll)
    if (silent && snapshot === _filesSnapshot) return;
    _filesSnapshot = snapshot;

    if (!files.length) {
      fileList.innerHTML = '<div class="empty-state">No files yet.</div>';
    } else {
      fileList.innerHTML = "";
      for (const f of files) {
        const row = el("div", "file-row");
        const isBin = f.path.endsWith(".bin");
        row.innerHTML = `
          <span class="file-path">${f.path}${isBin ? ' <span class="tag" style="font-size:10px;padding:1px 5px">BIN</span>' : ""}</span>
          <span class="file-size">${formatBytes(f.size_bytes)}</span>
        `;
        fileList.appendChild(row);
      }
    }
    if (statusEl) {
      const ts = new Date().toLocaleTimeString();
      statusEl.textContent = `updated ${ts}`;
    }
  } catch (_) {
    if (!silent) fileList.innerHTML = '<div class="empty-state">Error loading files.</div>';
  }
}

function _startFilesPoller(projectId) {
  _stopFilesPoller();
  _filesSnapshot = "";
  _filesPollTimer = setInterval(() => refreshProjectFiles(projectId, true), 5000);
}

function _stopFilesPoller() {
  if (_filesPollTimer) { clearInterval(_filesPollTimer); _filesPollTimer = null; }
}

async function openProject(p) {
  _currentProject = p;
  document.getElementById("proj-list-view").classList.add("hidden");
  document.getElementById("proj-detail-view").classList.remove("hidden");
  document.getElementById("projDetailName").textContent = p.name;
  document.getElementById("projDetailDesc").textContent = p.description || "";

  await refreshProjectFiles(p.id);
  _startFilesPoller(p.id);

  // Load project-scoped agent tasks
  _loadProjectTasks(p.id);

  // Apply project-level theme overrides
  api.projects.theme(p.id).then(t => {
    if (t.project_overrides && Object.keys(t.project_overrides).length)
      _applyProjectTheme(t.project_overrides);
  }).catch(() => {});

  const linkedIds = Array.isArray(p.devices) ? p.devices : [];
  await renderProjectDevices(p, linkedIds);
}

async function renderProjectDevices(project, linkedIds) {
  const devList = document.getElementById("projDeviceList");
  let allDevs;
  try { allDevs = await api.devices.list(); } catch (_) { allDevs = []; }
  const devMap = new Map(allDevs.map(d => [d.id, d]));

  devList.innerHTML = "";

  if (linkedIds.length) {
    for (const did of linkedIds) {
      const dev = devMap.get(did);
      const row = el("div", "file-row");
      row.innerHTML = `
        <span class="file-path">${dev ? (dev.name || did) : did}</span>
        <span class="file-size">${dev ? (dev.board || "?") : "not in fleet"}</span>
      `;
      const unlinkBtn = el("button", "btn btn-danger btn-sm", "Unlink");
      unlinkBtn.dataset.tip = "Remove this device from the project — the device stays in Fleet";
      unlinkBtn.style.marginLeft = "8px";
      unlinkBtn.onclick = async () => {
        const newIds = linkedIds.filter(id => id !== did);
        await api.projects.update(project.id, { devices: newIds }).catch(() => {});
        project.devices = newIds;
        renderProjectDevices(project, newIds);
      };
      row.appendChild(unlinkBtn);
      devList.appendChild(row);
    }
  } else {
    devList.appendChild(el("div", "empty-state", "No devices linked."));
  }

  const linkBtn = el("button", "btn btn-secondary btn-sm", "+ Link Device");
  linkBtn.dataset.tip = "Associate a fleet device with this project for OTA and agent targeting";
  linkBtn.style.marginTop = "10px";
  linkBtn.onclick = () => {
    const available = allDevs.filter(d => !linkedIds.includes(d.id));
    if (!available.length) {
      openModal("No Available Devices",
        '<div class="empty-state">All fleet devices are already linked, or fleet is empty.</div>',
        [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
      return;
    }
    const opts = available.map(d =>
      `<option value="${d.id}">${d.name || d.id} · ${d.board || "?"} ${d.paired ? "✓ paired" : "(unpaired)"}</option>`
    ).join("");
    openModal("Link Device to Project", `
      <div class="form-field">
        <label>Device</label>
        <select id="linkDevSel">${opts}</select>
      </div>
    `, [
      { label: "Link", cls: "btn btn-primary", action: async () => {
        const did = document.getElementById("linkDevSel").value;
        const newIds = [...linkedIds, did];
        await api.projects.update(project.id, { devices: newIds }).catch(() => {});
        project.devices = newIds;
        closeModal();
        renderProjectDevices(project, newIds);
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
  };
  devList.appendChild(linkBtn);
}

document.getElementById("btnProjNewTask").onclick = () => {
  if (!_currentProject) return;
  _openAgentTaskModal({
    context_type:  "project",
    context_id:    _currentProject.id,
    context_label: _currentProject.name,
  });
};

document.getElementById("btnProjBack").onclick = () => {
  _currentProject = null;
  _stopFilesPoller();
  _clearProjectTheme();
  const vsBtn = document.getElementById("btnOpenVSCode");
  if (vsBtn) vsBtn.style.display = "none";
  document.getElementById("proj-detail-view").classList.add("hidden");
  document.getElementById("proj-list-view").classList.remove("hidden");
};

document.getElementById("btnRefreshFiles").onclick = () => {
  if (_currentProject) refreshProjectFiles(_currentProject.id);
};

document.getElementById("btnProjTheme").onclick = async () => {
  if (!_currentProject) return;
  const current = await api.projects.theme(_currentProject.id).catch(() => ({ project_overrides: {} }));
  const existing = JSON.stringify(current.project_overrides || {}, null, 2);
  openModal(`Project Theme — ${_currentProject.name}`, `
    <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:10px">
      CSS custom property overrides applied while this project is active.<br>
      Example: <code>{"--color-accent":"#ff6600"}</code>
    </p>
    <div class="form-field">
      <textarea id="projThemeJson" rows="8" style="font-family:monospace;font-size:12px">${existing}</textarea>
    </div>
    <p id="projThemeStatus" style="font-size:12px;min-height:14px;margin-top:6px"></p>
  `, [
    { label: "Save & Apply", cls: "btn btn-primary", action: async () => {
      const raw = document.getElementById("projThemeJson")?.value || "{}";
      let overrides;
      try { overrides = JSON.parse(raw); } catch (_) {
        const s = document.getElementById("projThemeStatus");
        if (s) s.textContent = "Invalid JSON"; return;
      }
      await api.projects.setTheme(_currentProject.id, { theme_overrides: overrides }).catch(() => {});
      _applyProjectTheme(overrides);
      closeModal();
    }},
    { label: "Clear Overrides", cls: "btn btn-secondary", action: async () => {
      await api.projects.setTheme(_currentProject.id, { theme_overrides: {} }).catch(() => {});
      _clearProjectTheme();
      closeModal();
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
};

document.getElementById("btnProjDelete").onclick = async () => {
  if (!_currentProject) return;
  if (!confirm(`Delete project "${_currentProject.name}"? This cannot be undone.`)) return;
  await api.projects.delete(_currentProject.id).catch(() => {});
  _currentProject = null;
  _stopFilesPoller();
  document.getElementById("proj-detail-view").classList.add("hidden");
  document.getElementById("proj-list-view").classList.remove("hidden");
  loadProjects();
};

document.getElementById("btnNewProject").onclick = () => {
  openModal("New Project", `
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:14px;line-height:1.6">
      A project groups related firmware or hub code with linked devices and a custom theme.
      Create one for each device capability you want to build, then develop it in VS Code
      or hand it off to Agent Bench to build autonomously.
    </p>
    <div class="form-field">
      <label data-tip="Shown in the project list and used to identify this project in Agent Bench tasks">Name</label>
      <input type="text" id="newProjName" placeholder="e.g. Motion Sensor Node">
    </div>
    <div class="form-field">
      <label data-tip="Passed to the agent as context — describe the project purpose so the agent understands what it is building">Description (optional)</label>
      <textarea id="newProjDesc" rows="3" placeholder="e.g. PIR-based motion detection node — detects movement, blinks the onboard LED, and publishes a device.motion event to the hub"></textarea>
    </div>
  `, [
    { label: "Create", cls: "btn btn-primary", action: async () => {
      const name = document.getElementById("newProjName").value.trim();
      const desc = document.getElementById("newProjDesc").value.trim();
      if (!name) return;
      await api.projects.create({ name, description: desc || null });
      closeModal();
      loadProjects();
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
};

// ── Import existing PIO project ────────────────────────────────────────────

document.getElementById("btnImportProject").onclick = () => {
  openModal("Import PIO Project", `
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:14px;line-height:1.6">
      Copy an existing PlatformIO project folder into the hub. Build artifacts
      (<code>.pio/</code>) and Git history are excluded automatically. After import,
      use Agent Bench with the <strong>port-to-hub</strong> template to have the agent
      analyse the firmware and mirror its features as hub workers — with automatic
      ESP32 fallback when the hub is unreachable.
    </p>
    <div class="form-field">
      <label data-tip="Full path to the PlatformIO project folder on this machine — the folder that contains platformio.ini">Project Folder Path</label>
      <input type="text" id="importPath" placeholder="e.g. C:\\Users\\you\\Projects\\motion-sensor" style="font-family:monospace;font-size:12px">
    </div>
    <div class="form-field">
      <label data-tip="Name shown in the project list — defaults to the folder name if left blank">Project Name</label>
      <input type="text" id="importName" placeholder="e.g. Motion Sensor Node">
    </div>
    <div class="form-field">
      <label data-tip="Passed to the agent as context about what this project does">Description (optional)</label>
      <textarea id="importDesc" rows="2" placeholder="e.g. PIR motion sensor on GPIO 14 — reports to hub and blinks LED on trigger"></textarea>
    </div>
    <p id="importStatus" style="font-size:12px;color:var(--color-accent);margin-top:8px;min-height:14px"></p>
  `, [
    { label: "Import", cls: "btn btn-primary", action: async () => {
      const source_path = document.getElementById("importPath").value.trim();
      const rawName     = document.getElementById("importName").value.trim();
      const description = document.getElementById("importDesc").value.trim();
      const statusEl    = document.getElementById("importStatus");

      if (!source_path) { if (statusEl) statusEl.textContent = "Enter a folder path."; return; }

      // Derive name from last path component if not provided
      const name = rawName || source_path.replace(/[/\\]+$/, "").split(/[/\\]/).pop() || "Imported Project";

      if (statusEl) statusEl.textContent = "Copying files…";
      try {
        const result = await api.projects.import({ source_path, name, description: description || null });
        closeModal();
        openModal("Import Complete ✓", `
          <p style="margin-bottom:10px">
            <strong>${result.name}</strong> imported — ${result.file_count} files copied.
            ${result.has_platformio ? '<span style="color:var(--color-success)">✓ PlatformIO project detected.</span>' : ""}
          </p>
          <p style="font-size:13px;color:var(--color-text-muted);line-height:1.6">
            Next: open the project, link a device, then use
            <strong>Agent Bench → port-to-hub</strong> to have the agent analyse the
            firmware and wire up hub connectivity with standalone fallback.
          </p>
        `, [{ label: "Open Project", cls: "btn btn-primary", action: async () => {
          closeModal();
          const p = await api.projects.get(result.id).catch(() => null);
          if (p) openProject(p); else loadProjects();
        }}]);
      } catch (err) {
        if (statusEl) statusEl.textContent = "Error: " + err.message;
      }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
};

// ── Registry views (recipes, workers, cards) ───────────────────────────────

function renderRegistry(items, containerId, fields) {
  const el_ = document.getElementById(containerId);
  if (!items.length) {
    el_.innerHTML = '<div class="empty-state">Nothing found.</div>';
    return;
  }
  el_.innerHTML = "";
  for (const item of items) {
    const card = el("div", "reg-card");
    const title = item.display_name || item.name || item._folder || "—";
    const sub   = [item.category, item.runtime].filter(Boolean).join(" · ");
    const tags  = [
      ...(item.transports ? Object.keys(item.transports).map(t => `<span class="tag">${t}</span>`) : []),
      ...(item.inputs  || []).map(i => `<span class="tag">${i}</span>`),
      ...(item.outputs || []).map(o => `<span class="tag accent">${o}</span>`),
    ].slice(0, 6).join("");
    card.innerHTML = `
      <div class="reg-card-title">${title}</div>
      ${sub ? `<div class="reg-card-sub">${sub}</div>` : ""}
      <div class="tag-row">${tags}</div>
    `;
    el_.appendChild(card);
  }
}

async function loadRecipes() {
  const items = await api.recipes.list().catch(() => []);
  renderRegistry(items, "recipeList");
}

async function loadWorkers() {
  const items = await api.workers.list().catch(() => []);
  const el_ = document.getElementById("workerList");
  if (!items.length) { el_.innerHTML = '<div class="empty-state">Nothing found.</div>'; return; }
  el_.innerHTML = "";
  for (const item of items) {
    const card  = el("div", "reg-card");
    const title = item.display_name || item.name || item._folder || "—";
    const sub   = [item.category, item.runtime].filter(Boolean).join(" · ");
    const fs    = item.permissions?.filesystem || "—";
    const net   = item.permissions?.network    || "—";
    const tags  = [
      ...(item.inputs  || []).map(i => `<span class="tag">${i}</span>`),
      ...(item.outputs || []).map(o => `<span class="tag accent">${o}</span>`),
    ].slice(0, 6).join("");
    card.innerHTML = `
      <div class="reg-card-title">${title}</div>
      ${sub ? `<div class="reg-card-sub">${sub}</div>` : ""}
      <div class="tag-row">
        ${tags}
        <span class="tag" data-tip="Filesystem access level: ${fs}" style="opacity:.7">fs:${fs}</span>
        <span class="tag" data-tip="Network access level: ${net}" style="opacity:.7">net:${net}</span>
        ${item.quarantine ? '<span class="tag" data-tip="Imported or generated worker — runs sandboxed until reviewed" style="color:var(--color-warning)">quarantined</span>' : ""}
      </div>
    `;
    const testBtn = el("button", "btn btn-secondary btn-sm", "▶ Test");
    testBtn.dataset.tip = "Run this worker with test inputs and see the output immediately";
    testBtn.style.marginTop = "10px";
    testBtn.onclick = () => openWorkerTestModal(item);
    card.appendChild(testBtn);

    const taskBtn = el("button", "btn btn-secondary btn-sm", "⚡ Agent Task");
    taskBtn.dataset.tip = "Create an agent task scoped to this worker — modify, extend, or debug it";
    taskBtn.style.marginTop = "10px";
    taskBtn.style.marginLeft = "6px";
    taskBtn.onclick = () => _openAgentTaskModal({
      context_type: "worker",
      context_id:   wname,
      context_label: item.display_name || wname,
    });
    card.appendChild(taskBtn);
    el_.appendChild(card);
  }
}

function openWorkerTestModal(worker) {
  const wname = worker.name || worker._folder;
  openModal(`Test Worker — ${worker.display_name || wname}`, `
    <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:10px;line-height:1.6">
      Provide input values matching this worker's declared input schema, or leave as
      <code>{}</code> if it takes no inputs. The hub runs the worker in its sandbox and
      returns outputs, stdout, and any errors.
    </p>
    <div class="form-field">
      <label style="font-size:12px" data-tip="JSON object with keys matching the worker's declared inputs. Check the worker's manifest for the expected field names and types.">Inputs JSON</label>
      <textarea id="workerTestInputs" rows="5" style="font-family:monospace;font-size:12px">{}</textarea>
    </div>
    <div style="display:flex;align-items:center;gap:10px;margin-top:6px">
      <label style="font-size:12px" data-tip="Maximum seconds to wait before the hub kills the worker process and returns a timeout error">Timeout (s)</label>
      <input type="number" id="workerTestTimeout" value="30" min="1" max="60" style="width:60px">
    </div>
    <div id="workerTestResult" style="margin-top:14px"></div>
  `, [
    { label: "▶ Run", cls: "btn btn-primary", action: async () => {
      const rawInputs = document.getElementById("workerTestInputs")?.value || "{}";
      const timeout   = parseInt(document.getElementById("workerTestTimeout")?.value || "30");
      const resultEl  = document.getElementById("workerTestResult");
      let inputs;
      try { inputs = JSON.parse(rawInputs); } catch (_) { if (resultEl) resultEl.innerHTML = '<span style="color:var(--color-danger)">Invalid JSON in inputs</span>'; return; }
      if (resultEl) resultEl.innerHTML = '<span style="color:var(--color-text-muted)">Running…</span>';
      try {
        const r = await api.workers.test(wname, { inputs, timeout });
        const color = r.status === "ok" ? "var(--color-success)" : "var(--color-danger)";
        if (resultEl) resultEl.innerHTML = `
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
            <span style="color:${color};font-weight:700">${r.status.toUpperCase()}</span>
            <span style="font-size:12px;color:var(--color-text-muted)">exit ${r.exit_code} · ${r.duration_ms}ms</span>
          </div>
          ${r.outputs && Object.keys(r.outputs).length ? `<pre style="font-size:11px;max-height:120px;overflow:auto;background:var(--color-card);padding:8px;border-radius:6px">${JSON.stringify(r.outputs, null, 2)}</pre>` : ""}
          ${r.stderr  ? `<pre style="font-size:11px;max-height:80px;overflow:auto;color:var(--color-danger);background:var(--color-card);padding:6px;border-radius:6px;margin-top:6px">${r.stderr}</pre>` : ""}
        `;
      } catch (err) {
        if (resultEl) resultEl.innerHTML = `<span style="color:var(--color-danger)">${err.message}</span>`;
      }
    }},
    { label: "Close", cls: "btn btn-secondary", action: closeModal },
  ]);
}

async function loadCards() {
  const items = await api.cards.list().catch(() => []);
  renderRegistry(items, "cardList");
}

// ── Jobs view ──────────────────────────────────────────────────────────────

async function loadJobs() {
  const [jobs, workers] = await Promise.all([
    api.jobs.list().catch(() => []),
    api.workers.list().catch(() => []),
  ]);
  const workerMap = new Map(workers.map(w => [w.name || w._folder, w]));

  const listEl = document.getElementById("jobList");
  if (!jobs.length) {
    listEl.innerHTML = '<div class="empty-state">No jobs.</div>';
    return;
  }
  listEl.innerHTML = "";
  for (const j of jobs) {
    const row = el("div", "job-row");
    const w   = workerMap.get(j.worker_name);
    const cost = w?.resource_cost || {};

    const cpuColor = { high: "var(--color-danger)", medium: "var(--color-warning)", low: "var(--color-success)" };
    const costTags = Object.keys(cost).filter(k => k !== "realtime_safe").map(k => {
      const val   = String(cost[k]).toLowerCase();
      const color = k === "cpu" ? (cpuColor[val] || "var(--color-accent)") : "var(--color-text-muted)";
      return `<span class="tag" data-tip="${k} cost: ${val}" style="font-size:10px;color:${color}">${k}:${val}</span>`;
    }).join("");
    const rtSafe = cost.realtime_safe === false
      ? '<span class="tag" data-tip="This worker is not realtime-safe and may block the event loop" style="font-size:10px;color:var(--color-warning)">not-rt-safe</span>' : "";

    row.innerHTML = `
      <span class="job-status ${j.status}" data-tip="Job status: ${j.status}">${j.status}</span>
      <span style="font-weight:600;font-size:13px">${j.worker_name}</span>
      <span style="display:flex;gap:4px;align-items:center">${costTags}${rtSafe}</span>
      <span style="color:var(--color-text-muted);font-size:12px;flex:1">${j.id.slice(0,8)}</span>
      <span style="color:var(--color-text-muted);font-size:12px">${timeAgo(j.created)}</span>
    `;
    // Click to show outputs
    if (j.outputs || j.error) {
      row.style.cursor = "pointer";
      row.dataset.tip = "Click to view job outputs and timing details";
      row.onclick = () => {
        const detail = j.outputs ? JSON.stringify(JSON.parse(j.outputs || "{}"), null, 2) : "";
        openModal(`Job — ${j.worker_name}`, `
          <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:8px">
            Status: <b style="color:${j.status === 'done' ? 'var(--color-success)' : 'var(--color-danger)'}">${j.status}</b>
            · Created: ${timeAgo(j.created)}
            ${j.started ? `· Started: ${timeAgo(j.started)}` : ""}
            ${j.finished ? `· Finished: ${timeAgo(j.finished)}` : ""}
          </p>
          ${detail ? `<pre style="font-size:11px;max-height:200px;overflow:auto;background:var(--color-card);padding:8px;border-radius:6px">${detail}</pre>` : ""}
          ${j.error ? `<pre style="font-size:11px;color:var(--color-danger);max-height:120px;overflow:auto;background:var(--color-card);padding:8px;border-radius:6px;margin-top:6px">${j.error}</pre>` : ""}
        `, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
      };
    }
    listEl.appendChild(row);
  }
}

// ── OTA view ───────────────────────────────────────────────────────────────

async function loadOTA() {
  const [catalog, log] = await Promise.all([
    api.ota.catalog().catch(() => []),
    api.ota.log().catch(() => []),
  ]);
  const catEl = document.getElementById("otaCatalog");
  if (!catalog.length) {
    catEl.innerHTML = '<div class="empty-state">No firmware in catalog.</div>';
  } else {
    catEl.innerHTML = "";
    for (const fw of catalog) {
      const card = el("div", "reg-card");
      const goodBadge = fw.known_good
        ? `<span class="tag" style="background:rgba(26,175,100,.15);color:#1aaf64;border-color:rgba(26,175,100,.3)">✓ Known Good</span>`
        : "";
      const rbBadge = fw.rollback_target
        ? `<span class="tag" style="font-size:10px">↩ rb: ${fw.rollback_target}</span>` : "";
      card.innerHTML = `
        <div class="reg-card-title">${fw.board} — v${fw.version}</div>
        <div class="reg-card-sub">Channel: ${fw.channel} · ${formatBytes(fw.size_bytes)}</div>
        <div class="tag-row">
          <span class="tag" ${fw.sha256 ? `data-tip="Full SHA-256: ${fw.sha256}"` : ""}>${fw.sha256 ? fw.sha256.slice(0,12) + "…" : "no checksum"}</span>
          <span class="tag">${timeAgo(fw.uploaded)}</span>
          ${goodBadge}${rbBadge}
        </div>
      `;
      const btnRow = el("div", "");
      btnRow.style.cssText = "display:flex;gap:6px;margin-top:10px;flex-wrap:wrap";

      const pushBtn = el("button", "btn btn-secondary btn-sm", "Push to Device");
      pushBtn.dataset.tip = "Send this firmware to a paired device over the air";
      pushBtn.onclick = () => openPushModal(fw);
      btnRow.appendChild(pushBtn);

      if (!fw.known_good) {
        const goodBtn = el("button", "btn btn-secondary btn-sm", "✓ Mark Known Good");
        goodBtn.dataset.tip = "Mark this build as verified — safe to use as a rollback target";
        goodBtn.onclick = async () => {
          try {
            await api.ota.markGood(fw._folder || `${fw.board}-${fw.version}`);
            loadOTA();
          } catch (err) { alert("Error: " + err.message); }
        };
        btnRow.appendChild(goodBtn);
      }

      const rbBtn = el("button", "btn btn-secondary btn-sm", "↩ Set Rollback");
      rbBtn.dataset.tip = "Choose which firmware version to fall back to if a push fails";
      rbBtn.onclick = () => openRollbackTargetModal(fw, catalog);
      btnRow.appendChild(rbBtn);

      const rolloutBtn = el("button", "btn btn-secondary btn-sm", "⟳ Staged Rollout");
      rolloutBtn.dataset.tip = "Deploy to a percentage or subset of paired devices simultaneously";
      rolloutBtn.onclick = () => openRolloutModal(fw);
      btnRow.appendChild(rolloutBtn);

      card.appendChild(btnRow);
      catEl.appendChild(card);
    }
  }
  const logEl = document.getElementById("otaLog");
  if (!log.length) {
    logEl.innerHTML = '<div class="empty-state">No OTA events.</div>';
  } else {
    logEl.innerHTML = "";
    for (const entry of log.slice(0, 20)) {
      const row = el("div", "event-row");
      row.innerHTML = `
        <span class="event-type">${entry.action}</span>
        <span class="event-source">${entry.device_id}</span>
        <span style="color:var(--color-text-muted);font-size:12px">${entry.fw_version || "—"}</span>
        <span class="event-ts">${timeAgo(entry.timestamp)}</span>
      `;
      logEl.appendChild(row);
    }
  }
}

// ── OTA push modal ─────────────────────────────────────────────────────────

async function openPushModal(fw) {
  const devices = await api.devices.list().catch(() => []);
  const paired  = devices.filter(d => d.paired);
  if (!paired.length) {
    openModal("No Paired Devices",
      '<div class="empty-state">No paired devices available. Pair a device first from the Fleet view.</div>',
      [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    return;
  }
  const opts = paired.map(d =>
    `<option value="${d.id}" data-board="${d.board || ''}">${d.name || d.id} (${d.board || "unknown board"})</option>`
  ).join("");
  openModal(`Push Firmware — ${fw.board} v${fw.version}`, `
    <div class="form-field">
      <label data-tip="Only paired devices are eligible for OTA. Pair a device from the Fleet view if it does not appear here.">Target Device</label>
      <select id="pushDeviceSel">${opts}</select>
    </div>
    <div id="boardCompatWarn" class="compat-warning hidden">
      &#9888; Board mismatch: firmware is for <strong>${fw.board}</strong> but selected device reports a different board.
      <label style="display:block;margin-top:6px">
        <input type="checkbox" id="pushForce"> Override anyway (may brick device)
      </label>
    </div>
    <div class="form-field">
      <label data-tip="Logged in the OTA audit trail — use your name or a label that identifies who triggered this push (e.g. local, ci, patrick)">Operator</label>
      <input type="text" id="pushOperator" value="local" placeholder="your name or label">
    </div>
    <p style="font-size:12px;color:var(--color-text-muted);margin-top:8px">
      ${formatBytes(fw.size_bytes)} · SHA-256: ${fw.sha256 ? fw.sha256.slice(0, 16) + "…" : "—"}
    </p>
  `, [
    { label: "Push Firmware", cls: "btn btn-primary", action: async () => {
      const device_id = document.getElementById("pushDeviceSel").value;
      const operator  = document.getElementById("pushOperator").value.trim() || "local";
      const force     = document.getElementById("pushForce")?.checked ?? false;
      try {
        const result = await api.ota.push({ device_id, firmware_id: fw._folder, operator, force });
        closeModal();
        openModal(result.status === "ok" ? "Push Successful ✓" : "Push Failed", `
          <p><strong>Status:</strong>
            <span style="color:${result.status === 'ok' ? 'var(--color-success)' : 'var(--color-danger)'}">${result.status}</span>
          </p>
          ${result.response ? `<pre style="font-size:11px;margin-top:8px;overflow:auto;max-height:120px">${result.response}</pre>` : ""}
        `, [{ label: "Close", cls: "btn btn-primary", action: () => { closeModal(); loadOTA(); } }]);
      } catch (err) {
        alert("Push failed: " + err.message);
      }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);

  const sel  = document.getElementById("pushDeviceSel");
  const warn = document.getElementById("boardCompatWarn");
  const checkCompat = () => {
    const devBoard = sel.options[sel.selectedIndex]?.dataset?.board || "";
    warn.classList.toggle("hidden", !(fw.board && devBoard && fw.board !== devBoard));
  };
  sel.addEventListener("change", checkCompat);
  checkCompat();
}

function openRollbackTargetModal(fw, catalog) {
  const fwId    = fw._folder || `${fw.board}-${fw.version}`;
  const others  = catalog.filter(f => (f._folder || `${f.board}-${f.version}`) !== fwId);
  if (!others.length) {
    openModal("No Rollback Candidates", '<div class="empty-state">No other firmware in catalog to roll back to.</div>',
      [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    return;
  }
  const opts = others.map(f => {
    const id = f._folder || `${f.board}-${f.version}`;
    return `<option value="${id}">${f.board} v${f.version} (${f.channel})${f.known_good ? " ✓" : ""}</option>`;
  }).join("");
  const current = fw.rollback_target ? `<p style="font-size:12px;color:var(--color-text-muted);margin-bottom:8px">Current rollback target: <b>${fw.rollback_target}</b></p>` : "";
  openModal(`Set Rollback Target — ${fw.board} v${fw.version}`, `
    ${current}
    <div class="form-field">
      <label>Roll back to</label>
      <select id="rbTargetSel">${opts}</select>
    </div>
    <p style="font-size:12px;color:var(--color-text-muted);margin-top:6px">
      This sets the fallback firmware pushed automatically by a Rollback action.
    </p>
  `, [
    { label: "Save Rollback Target", cls: "btn btn-primary", action: async () => {
      const target = document.getElementById("rbTargetSel")?.value;
      if (!target) return;
      try {
        await api.ota.patchEntry(fwId, { rollback_target: target });
        closeModal();
        loadOTA();
      } catch (err) { alert("Error: " + err.message); }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
}

// ── OTA staged rollout modal ───────────────────────────────────────────────

async function openRolloutModal(fw) {
  const fwId   = fw._folder || `${fw.board}-${fw.version}`;
  const devices = await api.devices.list().catch(() => []);
  const paired  = devices.filter(d => d.paired);

  if (!paired.length) {
    openModal("No Paired Devices",
      '<div class="empty-state">No paired devices available. Pair a device first from the Fleet view.</div>',
      [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    return;
  }

  const checkboxes = paired.map(d => `
    <label style="display:flex;align-items:center;gap:8px;margin-bottom:6px;cursor:pointer;font-size:13px">
      <input type="checkbox" class="rollout-dev-check" value="${d.id}"
        ${d.board === fw.board ? "checked" : ""}>
      <span>${d.name || d.id}</span>
      <span style="color:var(--color-text-muted);font-size:11px">${d.board || "?"}</span>
      ${d.board !== fw.board ? '<span style="color:var(--color-warning);font-size:10px">⚠ board mismatch</span>' : ""}
    </label>
  `).join("");

  openModal(`Staged Rollout — ${fw.board} v${fw.version}`, `
    <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:14px">
      Select target devices and configure rollout parameters. Only paired devices are shown.
    </p>
    <div style="display:flex;gap:10px;margin-bottom:12px">
      <button class="btn btn-secondary btn-sm" id="rolloutSelAll">Select all</button>
      <button class="btn btn-secondary btn-sm" id="rolloutSelNone">None</button>
    </div>
    <div style="max-height:160px;overflow-y:auto;padding:8px;background:var(--color-card);border-radius:6px;border:1px solid var(--color-card-border);margin-bottom:12px">
      ${checkboxes}
    </div>
    <div class="form-field" style="margin-bottom:10px">
      <label>Percentage of selected (1–100, leave blank for all)</label>
      <input type="number" id="rolloutPct" min="1" max="100" placeholder="e.g. 25 for 25%">
    </div>
    <div class="form-field" style="margin-bottom:10px">
      <label>Operator</label>
      <input type="text" id="rolloutOperator" value="local" placeholder="your name or label">
    </div>
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:8px">
      <input type="checkbox" id="rolloutForce">
      Force (ignore board mismatch)
    </label>
    <div id="rolloutStatus" style="font-size:12px;min-height:14px;margin-top:4px"></div>
  `, [
    { label: "Launch Rollout", cls: "btn btn-primary", action: async () => {
      const checks = [...document.querySelectorAll(".rollout-dev-check:checked")];
      const device_ids = checks.map(c => c.value);
      if (!device_ids.length) {
        const s = document.getElementById("rolloutStatus");
        if (s) s.textContent = "Select at least one device."; return;
      }
      const pctRaw  = document.getElementById("rolloutPct")?.value?.trim();
      const pct     = pctRaw ? parseInt(pctRaw) : null;
      const operator = document.getElementById("rolloutOperator")?.value?.trim() || "local";
      const force   = document.getElementById("rolloutForce")?.checked ?? false;

      const statusEl = document.getElementById("rolloutStatus");
      if (statusEl) statusEl.textContent = `Pushing to ${device_ids.length} device(s)…`;

      try {
        const result = await api.otaRollout({ firmware_id: fwId, device_ids, pct, operator, force });
        closeModal();
        const ok   = result.succeeded ?? 0;
        const fail = result.failed ?? 0;
        const total = result.total ?? device_ids.length;
        openModal("Rollout Complete", `
          <div style="font-size:14px;margin-bottom:12px">
            <span style="color:var(--color-success);font-weight:700">${ok} succeeded</span>
            &nbsp;·&nbsp;
            <span style="color:${fail > 0 ? "var(--color-danger)" : "var(--color-text-muted)"};font-weight:${fail > 0 ? 700 : 400}">${fail} failed</span>
            &nbsp;of ${total} targeted
          </div>
          ${result.errors?.length ? `
            <div style="font-size:12px;color:var(--color-danger);background:var(--color-card);padding:8px;border-radius:6px;max-height:120px;overflow:auto">
              ${result.errors.join("<br>")}
            </div>` : ""}
        `, [{ label: "Close", cls: "btn btn-primary", action: () => { closeModal(); loadOTA(); } }]);
      } catch (err) {
        const s = document.getElementById("rolloutStatus");
        if (s) s.textContent = "Error: " + err.message;
      }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);

  document.getElementById("rolloutSelAll")?.addEventListener("click", () => {
    document.querySelectorAll(".rollout-dev-check").forEach(c => c.checked = true);
  });
  document.getElementById("rolloutSelNone")?.addEventListener("click", () => {
    document.querySelectorAll(".rollout-dev-check").forEach(c => c.checked = false);
  });
}

// ── Design view ────────────────────────────────────────────────────────────

async function loadDesign() {
  const tokens = await api.design.tokens().catch(() => ({}));
  const grid = document.getElementById("tokenList");
  grid.innerHTML = "";
  for (const [key, value] of Object.entries(tokens)) {
    const row = el("div", "token-row");
    const isColor = value.startsWith("#") || value.startsWith("rgb");
    row.innerHTML = `
      ${isColor ? `<span class="token-swatch" style="background:${value}"></span>` : ""}
      <span class="token-name">${key}</span>
      <span class="token-value">${value}</span>
    `;
    grid.appendChild(row);
  }
  if (!Object.keys(tokens).length) {
    grid.innerHTML = '<div class="empty-state">No tokens loaded.</div>';
  }
}

// ── Events view ────────────────────────────────────────────────────────────

async function loadEvents() {
  const events = await api.events.list({ limit: 50 }).catch(() => []);
  const listEl = document.getElementById("eventList");
  if (!events.length) {
    listEl.innerHTML = '<div class="empty-state">No events.</div>';
    return;
  }
  listEl.innerHTML = "";
  for (const evt of events) {
    const row = el("div", "event-row");
    row.innerHTML = `
      <span class="event-type">${evt.event_type}</span>
      <span class="event-source">${evt.source || "—"}</span>
      <span style="font-size:12px;color:var(--color-text-muted);flex:1">
        ${typeof evt.payload === "object" ? JSON.stringify(evt.payload).slice(0, 80) : evt.payload || ""}
      </span>
      <span class="event-ts">${timeAgo(evt.timestamp)}</span>
    `;
    listEl.appendChild(row);
  }
}

// ── Rules view ─────────────────────────────────────────────────────────────

const _ACTION_LABELS = {
  log_event:    "Log Event",
  run_worker:   "Run Worker",
  webhook:      "Webhook POST",
  theme_change: "Theme Token Override",
};

async function loadRules() {
  const rules = await api.rules.list().catch(() => []);
  const listEl = document.getElementById("ruleList");
  if (!rules.length) {
    listEl.innerHTML = '<div class="empty-state">No rules yet. Rules fire automatically when matching events are published.</div>';
    return;
  }
  listEl.innerHTML = "";
  for (const r of rules) {
    const row = el("div", "rule-row");
    const cfg = r.action_config || {};
    const cfgSummary = r.action_type === "run_worker" ? cfg.worker_name || "?"
                     : r.action_type === "webhook"    ? cfg.url || "?"
                     : "";
    row.innerHTML = `
      <div class="rule-enabled-dot ${r.enabled ? "on" : "off"}" data-tip="${r.enabled ? "Rule is active and fires on matching events" : "Rule is disabled — no actions will fire"}"></div>
      <div class="rule-info">
        <div class="rule-name">${r.name}</div>
        <div class="rule-meta">
          on <strong>${r.event_type}</strong>
          ${r.source_filter ? `from <em>${r.source_filter}</em>` : ""}
          → ${_ACTION_LABELS[r.action_type] || r.action_type}
          ${cfgSummary ? `<code>${cfgSummary}</code>` : ""}
          ${r.last_triggered ? `· last: ${timeAgo(r.last_triggered)}` : ""}
        </div>
      </div>
    `;
    const toggleBtn = el("button", `btn btn-secondary btn-sm`);
    toggleBtn.textContent = r.enabled ? "Disable" : "Enable";
    toggleBtn.dataset.tip = r.enabled ? "Disable this rule" : "Enable this rule";
    toggleBtn.onclick = async () => {
      await api.rules.update(r.id, { enabled: !r.enabled }).catch(() => {});
      loadRules();
    };
    const delBtn = el("button", "btn btn-danger btn-sm");
    delBtn.innerHTML = "&#x2715;";
    delBtn.dataset.tip = "Delete this automation rule";
    delBtn.onclick = async () => {
      if (!confirm(`Delete rule "${r.name}"?`)) return;
      await api.rules.delete(r.id).catch(() => {});
      loadRules();
    };
    const actions = el("div", "device-actions");
    actions.appendChild(toggleBtn);
    actions.appendChild(delBtn);
    row.appendChild(actions);
    listEl.appendChild(row);
  }
}

document.getElementById("btnNewRule").onclick = () => {
  openModal("New Automation Rule", `
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:14px;line-height:1.6">
      Rules fire automatically when matching events arrive from a device or the hub.
      Use them to run workers, call webhooks, or change the UI theme in response to
      sensor readings, alerts, or state changes.
    </p>
    <div class="form-field">
      <label data-tip="A descriptive label shown in the rule list">Rule Name</label>
      <input type="text" id="ruleNameInput" placeholder="e.g. Alert on motion detected">
    </div>
    <div class="form-field">
      <label data-tip="Matches the event_type field exactly. Common types: device.checkin, device.motion, device.alert, sensor.reading, firmware.update">Trigger Event Type</label>
      <input type="text" id="ruleEventType" placeholder="e.g. device.motion">
    </div>
    <div class="form-field">
      <label data-tip="Only fire when the event source matches this value — usually a device ID or device name. Leave blank to match events from any device.">Source Filter (optional — blank matches any)</label>
      <input type="text" id="ruleSourceFilter" placeholder="e.g. kitchen-sensor-abc123">
    </div>
    <div class="form-field">
      <label data-tip="What to do when this rule fires">Action</label>
      <select id="ruleActionType">
        <option value="log_event">Log Event — record in event log, no side effects</option>
        <option value="run_worker">Run Worker — execute a hub code module</option>
        <option value="webhook">Webhook POST — call an external HTTP endpoint</option>
        <option value="theme_change">Theme Override — temporarily change the UI appearance</option>
      </select>
    </div>
    <div class="form-field" id="ruleActionConfigField">
      <label id="ruleActionConfigLabel">Worker Name</label>
      <input type="text" id="ruleActionConfig" placeholder="opencv-motion-tagger">
    </div>
    <div class="form-field hidden" id="ruleThemeConfigField">
      <label>Token Overrides (JSON)</label>
      <textarea id="ruleThemeTokens" rows="4" style="font-family:monospace;font-size:12px" placeholder='{"--color-accent":"#ff4400","--color-background":"#1a0800"}'></textarea>
      <div style="display:flex;align-items:center;gap:10px;margin-top:6px">
        <label style="font-size:12px">Duration (minutes)</label>
        <input type="number" id="ruleThemeDuration" value="5" min="1" max="1440" style="width:70px">
      </div>
    </div>
  `, [
    { label: "Create Rule", cls: "btn btn-primary", action: async () => {
      const name        = document.getElementById("ruleNameInput").value.trim();
      const event_type  = document.getElementById("ruleEventType").value.trim();
      const source_filter = document.getElementById("ruleSourceFilter").value.trim() || null;
      const action_type = document.getElementById("ruleActionType").value;
      const cfgRaw      = document.getElementById("ruleActionConfig").value.trim();
      if (!name || !event_type) return;
      let action_config = {};
      if (action_type === "run_worker")  action_config = { worker_name: cfgRaw };
      if (action_type === "webhook")     action_config = { url: cfgRaw };
      if (action_type === "theme_change") {
        const rawTokens  = document.getElementById("ruleThemeTokens")?.value || "{}";
        const duration   = parseInt(document.getElementById("ruleThemeDuration")?.value || "5");
        let tokens;
        try { tokens = JSON.parse(rawTokens); } catch (_) { alert("Invalid JSON in token overrides"); return; }
        action_config = { tokens, duration_minutes: duration };
      }
      await api.rules.create({ name, event_type, source_filter, action_type, action_config });
      closeModal();
      loadRules();
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);

  // Update config field label when action type changes
  const sel = document.getElementById("ruleActionType");
  const cfgField   = document.getElementById("ruleActionConfigField");
  const cfgLabel   = document.getElementById("ruleActionConfigLabel");
  const cfgInput   = document.getElementById("ruleActionConfig");
  const themeField = document.getElementById("ruleThemeConfigField");
  const updateLabel = () => {
    cfgField.style.display   = "";
    themeField.classList.add("hidden");
    if (sel.value === "log_event")    { cfgField.style.display = "none"; }
    else if (sel.value === "run_worker")   { cfgLabel.textContent = "Worker Name"; cfgInput.placeholder = "opencv-motion-tagger"; }
    else if (sel.value === "webhook")      { cfgLabel.textContent = "Webhook URL"; cfgInput.placeholder = "http://homeassistant.local/hook"; }
    else if (sel.value === "theme_change") { cfgField.style.display = "none"; themeField.classList.remove("hidden"); }
  };
  sel.addEventListener("change", updateLabel);
  updateLabel();
};

// ── Agent Bench view ───────────────────────────────────────────────────────

let _abCurrentTask = null;
let _abStatusFilter = "";
let _abPollTimer = null;

function _abStatusClass(status) {
  return "ab-status-badge ab-status-" + (status || "draft");
}

function _abStatusLabel(status) {
  const labels = {
    draft: "Draft", running: "Running", awaiting_review: "Review",
    approved: "Approved", rejected: "Rejected", needs_changes: "Changes", merged: "Merged",
    awaiting_input: "Waiting",
  };
  return labels[status] || status;
}

const _AB_TEMPLATE_LABELS = {
  "firmware-feature": "Firmware Feature",
  "hub-feature":      "Hub Feature",
  "port-to-hub":      "Port to Hub",
  "recipe-feature":   "Recipe Feature",
  "bug-fix":          "Bug Fix",
  "custom":           "Custom",
};

const _templatePlaceholders = {
  "firmware-feature": "e.g. Add a PIR motion sensor on GPIO pin 14. When triggered, blink the onboard LED 3 times and publish a device.motion event to the hub with device name, sensor pin, and UTC timestamp.",
  "hub-feature":      "e.g. Add a GET /api/sensors/latest endpoint that returns the most recent sensor reading for a given device ID from the events table.",
  "port-to-hub":      "e.g. This project has a web server with /api/temperature and /api/motion endpoints. Port these to hub workers that store readings in the events table. Add hub check-in to the firmware and fall back to the device web server when the hub is unreachable (>10s timeout).",
  "recipe-feature":   "e.g. Create a recipe that reads temperature from device.sensor events and forwards readings above 30°C to a webhook at http://homeassistant.local/api/webhook/hot-alert.",
  "bug-fix":          "e.g. The firmware reboots after ~2 hours. The serial log shows heap exhaustion near the JSON serialisation block around line 142 of main.cpp — investigate and fix the memory leak.",
  "custom":           "e.g. Describe what you want to build or change — include file names, variable names, or API details if you know them.",
};

async function loadAgentBench() {
  _stopAbPoller();

  // Silently check if enabled (no alert on 503 — expected when disabled)
  let config;
  try {
    config = await api.agentBench.getConfig();
  } catch (_) {
    config = { enabled: false };
  }

  const disabledEl  = document.getElementById("ab-disabled-notice");
  const listEl      = document.getElementById("ab-list-view");
  const detailEl    = document.getElementById("ab-detail-view");

  if (!config.enabled) {
    disabledEl.classList.remove("hidden");
    listEl.classList.add("hidden");
    detailEl.classList.add("hidden");
    return;
  }

  disabledEl.classList.add("hidden");
  detailEl.classList.add("hidden");
  listEl.classList.remove("hidden");

  await _abLoadTaskList();
}

async function _abLoadTaskList() {
  const listEl = document.getElementById("abTaskList");
  listEl.innerHTML = '<div class="empty-state">Loading…</div>';
  const params = _abStatusFilter ? { status: _abStatusFilter } : {};
  const tasks = await api.agentBench.listTasks(params).catch(() => []);
  if (!tasks.length) {
    listEl.innerHTML = '<div class="empty-state">No agent tasks yet. Click "+ New Task" to get started.</div>';
    return;
  }
  listEl.innerHTML = "";
  for (const t of tasks) {
    const card = el("div", "ab-task-card");
    const ctxBadge = t.context_type
      ? `<span class="ab-context-badge" data-tip="Scoped to ${t.context_type}: ${t.context_id || ''}">${t.context_type === "project" ? "🗂" : "⚙"} ${(t.context_id || "").slice(0,10)}</span>`
      : (t.project_id ? `<span class="ab-context-badge" data-tip="Linked to project ${t.project_id.slice(0,8)}">🗂</span>` : "");
    const threadBadge = t.parent_task_id
      ? `<span class="ab-thread-badge" data-tip="Follow-up in a task thread">↩ thread</span>` : "";
    card.innerHTML = `
      <div class="ab-task-info">
        <div class="ab-task-title">${t.title}</div>
        <div class="ab-task-meta">${_AB_TEMPLATE_LABELS[t.template] || t.template} · ${t.lane} lane · ${timeAgo(t.updated)}${ctxBadge}${threadBadge}</div>
      </div>
      <span class="${_abStatusClass(t.status)}" data-tip="Task status: ${t.status}">${_abStatusLabel(t.status)}</span>
    `;
    card.onclick = () => _abOpenTask(t.id);
    listEl.appendChild(card);
  }
}

async function _abOpenTask(taskId) {
  const task = await api.agentBench.getTask(taskId).catch(() => null);
  if (!task) return;
  _abCurrentTask = task;

  document.getElementById("ab-list-view").classList.add("hidden");
  document.getElementById("ab-detail-view").classList.remove("hidden");
  document.getElementById("abDetailTitle").textContent = task.title;

  const statusEl = document.getElementById("abDetailStatus");
  statusEl.className = _abStatusClass(task.status);
  statusEl.textContent = _abStatusLabel(task.status);

  const metaEl = document.getElementById("abThreadMeta");
  const allowed = JSON.parse(task.allowed_paths || "[]");
  metaEl.innerHTML = `
    <span data-tip="Task template — determines which codebase sections the agent focuses on">Template: <strong>${_AB_TEMPLATE_LABELS[task.template] || task.template}</strong></span>
    <span data-tip="Development lane — agents always work in dev, never production">Lane: <strong>${task.lane}</strong></span>
    ${task.adapter_id ? `<span data-tip="Adapter used to run the agent">Adapter: <strong>${task.adapter_id}</strong></span>` : ""}
    ${allowed.length ? `<span data-tip="Number of directory paths the agent is allowed to modify">Paths: <strong>${allowed.length}</strong></span>` : ""}
  `;

  await _abLoadThread(taskId);
  await _abSetupAdapterSelect();
  _abUpdateRunControls(task);

  _startAbPoller(taskId);
}

async function _abLoadThread(taskId) {
  const msgs = await api.agentBench.getMessages(taskId).catch(() => []);
  const threadEl = document.getElementById("abThread");
  threadEl.innerHTML = "";
  if (!msgs.length) {
    threadEl.innerHTML = '<div class="empty-state" style="font-size:12px">No messages yet.</div>';
    return;
  }
  for (const m of msgs) {
    const div = el("div", `ab-msg ab-msg-${m.role}`);
    const ts = el("div", "ab-msg-ts", timeAgo(m.timestamp));
    if (m.role === "system") {
      div.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
          <span style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--color-accent)">Prompt Generated</span>
          <button class="btn btn-secondary btn-sm" style="padding:3px 9px;font-size:11px">Copy Prompt</button>
          <button class="btn btn-secondary btn-sm" style="padding:3px 9px;font-size:11px">View Full</button>
        </div>
        <div style="font-size:12px;color:var(--color-text-muted);font-style:italic">The prompt is ready — copy it into Claude, ChatGPT, or another AI, apply the file changes it describes, then paste the response back in the panel below.</div>
      `;
      const [copyBtn, viewBtn] = div.querySelectorAll("button");
      copyBtn.onclick = () => {
        navigator.clipboard?.writeText(m.content).then(() => {
          const orig = copyBtn.textContent; copyBtn.textContent = "Copied!"; setTimeout(() => copyBtn.textContent = orig, 1500);
        }).catch(() => {});
      };
      viewBtn.onclick = () => openModal("Agent Prompt", `
        <pre style="font-size:11px;white-space:pre-wrap;word-break:break-word;max-height:400px;overflow:auto;line-height:1.5">${m.content}</pre>
      `, [
        { label: "Copy to Clipboard", cls: "btn btn-primary", action: () => {
          navigator.clipboard?.writeText(m.content).catch(() => {});
          closeModal();
        }},
        { label: "Close", cls: "btn btn-secondary", action: closeModal },
      ]);
    } else {
      div.textContent = m.content.slice(0, 2000) + (m.content.length > 2000 ? "\n…(truncated)" : "");
    }
    div.appendChild(ts);
    threadEl.appendChild(div);
  }
  threadEl.scrollTop = threadEl.scrollHeight;
}

async function _abSetupAdapterSelect() {
  const sel = document.getElementById("abAdapterSelect");
  const desc = document.getElementById("abAdapterDesc");
  sel.innerHTML = "";
  let adapters = [];
  try {
    adapters = await api.agentBench.listAdapters();
  } catch (_) {
    adapters = [{ name: "manual", display_name: "Manual (Copy/Paste)", installed: true }];
  }
  for (const a of adapters) {
    const opt = document.createElement("option");
    opt.value = a.name;
    opt.textContent = a.display_name + (a.installed === false ? " — not installed" : "");
    if (a.installed === false) opt.disabled = true;
    sel.appendChild(opt);
  }
  if (_abCurrentTask?.adapter_id) sel.value = _abCurrentTask.adapter_id;
  const updateDesc = () => { if (desc) desc.textContent = _ADAPTER_DESCRIPTIONS[sel.value] || ""; };
  sel.removeEventListener("change", sel._descHandler);
  sel._descHandler = updateDesc;
  sel.addEventListener("change", updateDesc);
  updateDesc();
}

const _ADAPTER_DESCRIPTIONS = {
  "manual":          "Manual — hub generates the prompt; you copy it into any AI chat (Claude, ChatGPT, etc.), apply the file changes yourself, then paste the response back here.",
  "codex-cli":       "Codex CLI — runs automatically: hub executes the local codex CLI which reads the prompt, edits files, and reports back. Requires codex installed and OPENAI_API_KEY set.",
  "claude-code-cli": "Claude Code CLI — runs automatically: hub executes the local claude CLI which reads the prompt, edits files directly, and reports back. Most capable automated option.",
};

function _abUpdateRunControls(task) {
  const runPanel    = document.getElementById("abRunPanel");
  const pastePanel  = document.getElementById("abPastePanel");
  const reviewPanel = document.getElementById("abReviewPanel");
  const adapterDesc = document.getElementById("abAdapterDesc");

  const canRun     = ["draft", "needs_changes"].includes(task.status);
  const needsPaste = task.status === "awaiting_review" && task.latest_run?.status === "awaiting_input";
  // Only show review AFTER the response is submitted (run no longer awaiting_input)
  const needsReview = task.status === "awaiting_review" && !needsPaste;

  runPanel.style.display = canRun ? "" : "none";
  pastePanel.classList.toggle("hidden", !needsPaste);
  reviewPanel.classList.toggle("hidden", !needsReview);

  // Update adapter description
  if (adapterDesc) {
    const sel = document.getElementById("abAdapterSelect");
    adapterDesc.textContent = sel ? (_ADAPTER_DESCRIPTIONS[sel.value] || "") : "";
  }
}

function _startAbPoller(taskId) {
  _stopAbPoller();
  _abPollTimer = setInterval(async () => {
    const task = await api.agentBench.getTask(taskId).catch(() => null);
    if (!task) return;
    _abCurrentTask = task;
    const statusEl = document.getElementById("abDetailStatus");
    if (statusEl) {
      statusEl.className = _abStatusClass(task.status);
      statusEl.textContent = _abStatusLabel(task.status);
    }
    _abUpdateRunControls(task);
    if (["running"].includes(task.status)) {
      await _abLoadThread(taskId);
    }
  }, 3000);
}

function _stopAbPoller() {
  if (_abPollTimer) { clearInterval(_abPollTimer); _abPollTimer = null; }
}

// Agent Bench event wiring (runs once DOM is ready)
function _abWireEvents() {
  document.getElementById("btnAbBack").onclick = () => {
    _stopAbPoller();
    _abCurrentTask = null;
    document.getElementById("ab-detail-view").classList.add("hidden");
    document.getElementById("ab-list-view").classList.remove("hidden");
    _abLoadTaskList();
  };

  document.getElementById("btnAbEnable").onclick = async () => {
    try {
      await api.agentBench.updateConfig({ enabled: true, require_human_review: true, allowed_adapters: ["manual"] });
      await loadAgentBench();
    } catch (err) { alert("Error: " + err.message); }
  };

  document.getElementById("btnAbNewTask").onclick = () => _openAgentTaskModal();

  const _PORTAL_INSTALLABLE = new Set(["pio", "codex", "claude"]);

  // ── Doctor metadata ────────────────────────────────────────────────────────
  // tier: "required" | "pick-one" | "optional"
  const _DOCTOR_META = {
    // Tools
    python: {
      label: "Python",
      tier: "required",
      desc: "Runs the hub server itself. It's already present — you're using it right now.",
    },
    git: {
      label: "Git",
      tier: "optional",
      desc: "Used to snapshot and diff files before/after an agent run. Without it the Diff view won't show changes for CLI adapter runs. GitHub Desktop's bundled git is detected automatically.",
    },
    pio: {
      label: "PlatformIO",
      tier: "optional",
      desc: "Required only for firmware-feature and bug-fix tasks that build or flash ESP32 firmware. Not needed for hub-feature, recipe, or worker tasks.",
    },
    docker: {
      label: "Docker",
      tier: "optional",
      desc: "Not currently used. Reserved for future sandboxed agent execution environments. Safe to skip.",
    },
    codex: {
      label: "OpenAI Codex CLI",
      tier: "pick-one",
      desc: "One of two CLI adapters for automated agent runs. Requires an OpenAI API key. Install either this or Claude CLI — or use the Manual adapter which needs neither.",
    },
    claude: {
      label: "Claude Code CLI",
      tier: "pick-one",
      desc: "One of two CLI adapters for automated agent runs. Uses your Anthropic account. Install either this or Codex CLI — or use the Manual adapter which needs neither.",
    },
    node: {
      label: "Node.js",
      tier: "optional",
      desc: "Needed to install Codex CLI or Claude Code CLI via npm. Not required if you only use the Manual adapter.",
    },
    // Adapters
    manual: {
      label: "Manual (Copy/Paste)",
      tier: "optional",
      desc: "Always available, no install required. Copy the generated prompt into any AI chat, paste the response back. Great for one-off tasks or when CLI adapters aren't set up.",
    },
    "codex-cli": {
      label: "Codex CLI Adapter",
      tier: "pick-one",
      desc: "Runs tasks fully automatically via the local codex CLI. Needs Codex installed and an OPENAI_API_KEY environment variable set.",
    },
    "claude-code-cli": {
      label: "Claude Code CLI Adapter",
      tier: "pick-one",
      desc: "Runs tasks fully automatically via the local claude CLI. Needs Claude Code installed and an Anthropic account. The most capable automated option.",
    },
  };

  const _TIER_LABELS = { required: "Required", "pick-one": "Pick One", optional: "Optional" };

  // Tooltip positioning — appears to the right of the hovered row, flips left if near edge
  function _showDoctorTooltip(rowEl, key) {
    const meta = _DOCTOR_META[key];
    if (!meta) return;
    const tt     = document.getElementById("doctorTooltip");
    const badge  = document.getElementById("doctorTtBadge");
    const name   = document.getElementById("doctorTtName");
    const desc   = document.getElementById("doctorTtDesc");
    badge.textContent = _TIER_LABELS[meta.tier] || meta.tier;
    badge.className   = `doctor-tt-badge ${meta.tier}`;
    name.textContent  = meta.label;
    desc.textContent  = meta.desc;
    tt.classList.remove("hidden");

    const rect    = rowEl.getBoundingClientRect();
    const margin  = 10;
    const ttW     = 260;
    let left = rect.right + margin;
    let top  = rect.top;
    if (left + ttW > window.innerWidth - margin) left = rect.left - ttW - margin;
    // After un-hiding, clamp vertical so it doesn't go off bottom
    requestAnimationFrame(() => {
      const ttH = tt.offsetHeight;
      if (top + ttH > window.innerHeight - margin) top = window.innerHeight - ttH - margin;
      tt.style.left = Math.max(margin, left) + "px";
      tt.style.top  = Math.max(margin, top)  + "px";
    });
  }

  function _hideDoctorTooltip() {
    document.getElementById("doctorTooltip")?.classList.add("hidden");
  }

  async function _runDoctor() {
    const d = await api.agentBench.doctor().catch(err => ({ error: err.message }));
    if (d.error) {
      openModal("Doctor", `<p class="empty-state">${d.error}</p>`,
        [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
      return;
    }

    const toolRows = Object.entries(d.tools || {}).map(([name, info]) => {
      const ok = info.found;
      const canInstall = !ok && _PORTAL_INSTALLABLE.has(name);
      const installBtn = canInstall
        ? `<button class="btn btn-secondary btn-sm doctor-install-btn" data-tool="${name}" style="margin-left:auto">Install</button>` : "";
      const hint = !ok && !canInstall && info.install_hint
        ? `<div class="doctor-hint"><code>${info.install_hint}</code></div>` : "";
      return `<div class="doctor-row" data-tool="${name}">
        <span class="doctor-icon ${ok ? "ok" : "miss"}">${ok ? "✓" : "✗"}</span>
        <span class="doctor-name">${name}</span>
        <span class="doctor-val">${ok ? (info.version || "found") : '<span style="color:var(--color-danger)">not found</span>'}</span>
        ${installBtn}
      </div>${hint}`;
    }).join("");

    const adapterRows = Object.entries(d.adapters_ready || {}).map(([k, v]) => {
      const ready = (typeof v === "object") ? v.ready : v;
      const hint  = !ready && v?.install_hint
        ? `<div class="doctor-hint"><code>${v.install_hint}</code></div>` : "";
      return `<div class="doctor-row" data-tool="${k}">
        <span class="doctor-icon ${ready ? "ok" : "miss"}">${ready ? "✓" : "✗"}</span>
        <span class="doctor-name">${k}</span>
        <span class="doctor-val" style="color:${ready ? "var(--color-success)" : "var(--color-danger)"}">${ready ? "ready" : "not installed"}</span>
      </div>${hint}`;
    }).join("");

    openModal("Agent Bench Doctor", `
      <p class="doctor-section-label">Tools</p>
      ${toolRows}
      <p class="doctor-section-label" style="margin-top:16px">Adapters</p>
      ${adapterRows}
    `, [{ label: "Close", cls: "btn btn-secondary", action: () => { _hideDoctorTooltip(); closeModal(); } }]);

    // Wire tooltip hover on all doctor rows
    document.querySelectorAll(".doctor-row[data-tool]").forEach(row => {
      row.addEventListener("mouseenter", () => _showDoctorTooltip(row, row.dataset.tool));
      row.addEventListener("mouseleave", _hideDoctorTooltip);
    });

    // Wire Install buttons (after innerHTML is set by openModal)
    document.querySelectorAll(".doctor-install-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const tool = btn.dataset.tool;
        btn.disabled = true;
        btn.textContent = "Installing…";
        _hideDoctorTooltip();

        let result;
        try {
          result = await api.agentBench.install(tool);
        } catch (err) {
          result = { ok: false, output: err.message, now_found: false };
        }

        const color   = result.ok ? "var(--color-success)" : "var(--color-danger)";
        const headline = result.ok
          ? `✓ ${result.display_name || tool} installed — ${result.version || ""}`
          : `✗ Install failed (exit ${result.exit_code ?? "?"})`;

        openModal(`Install — ${tool}`, `
          <p style="color:${color};font-weight:700;margin-bottom:12px">${headline}</p>
          <pre style="font-size:11px;white-space:pre-wrap;word-break:break-word;max-height:260px;overflow-y:auto;background:var(--color-card);border:1px solid var(--color-card-border);border-radius:6px;padding:10px;line-height:1.5">${(result.output || "(no output)").replace(/</g,"&lt;")}</pre>
        `, [
          { label: "Run Doctor Again", cls: "btn btn-primary", action: () => { closeModal(); _runDoctor(); } },
          { label: "Close", cls: "btn btn-secondary", action: closeModal },
        ]);
      });
    });
  }

  document.getElementById("btnAbDoctor").onclick = _runDoctor;

  document.getElementById("btnAbSettings").onclick = async () => {
    let cfg = { enabled: true, allow_dev_device_deploy: false, require_human_review: true, allowed_adapters: ["manual"] };
    try { cfg = await api.agentBench.getConfig(); } catch (_) {}
    openModal("Agent Bench Settings", `
      <label style="display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:12px">
        <input type="checkbox" id="abSetEnabled" ${cfg.enabled ? "checked" : ""}> Enabled
      </label>
      <label style="display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:12px">
        <input type="checkbox" id="abSetReview" ${cfg.require_human_review ? "checked" : ""}> Require human review before merge
      </label>
      <label style="display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:12px">
        <input type="checkbox" id="abSetDevDeploy" ${cfg.allow_dev_device_deploy ? "checked" : ""}> Allow dev device deployment
      </label>
      <div class="form-field">
        <label>Allowed adapters (comma-separated)</label>
        <input type="text" id="abSetAdapters" value="${(cfg.allowed_adapters || ["manual"]).join(",")}">
      </div>
      <p style="font-size:11px;color:var(--color-text-muted);margin-top:6px">Restart hub after saving for changes to take full effect.</p>
    `, [
      { label: "Save", cls: "btn btn-primary", action: async () => {
        const enabled = document.getElementById("abSetEnabled").checked;
        const require_human_review = document.getElementById("abSetReview").checked;
        const allow_dev_device_deploy = document.getElementById("abSetDevDeploy").checked;
        const adaptersRaw = document.getElementById("abSetAdapters").value.trim();
        const allowed_adapters = adaptersRaw ? adaptersRaw.split(",").map(s => s.trim()).filter(Boolean) : ["manual"];
        try {
          await api.agentBench.updateConfig({ enabled, require_human_review, allow_dev_device_deploy, allowed_adapters });
          closeModal();
          await loadAgentBench();
        } catch (err) { alert("Error: " + err.message); }
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
  };

  document.getElementById("btnAbRun").onclick = async () => {
    if (!_abCurrentTask) return;
    const adapter_id = document.getElementById("abAdapterSelect").value;
    try {
      const result = await api.agentBench.runTask(_abCurrentTask.id, { adapter_id });
      if (result.adapter === "manual") {
        document.getElementById("abPastePanel").classList.remove("hidden");
        document.getElementById("abRunPanel").style.display = "none";
        await _abLoadThread(_abCurrentTask.id);
        const task = await api.agentBench.getTask(_abCurrentTask.id).catch(() => _abCurrentTask);
        _abCurrentTask = task;
        _abUpdateRunControls(task);
      } else {
        const statusEl = document.getElementById("abDetailStatus");
        if (statusEl) { statusEl.className = _abStatusClass("running"); statusEl.textContent = "Running"; }
      }
    } catch (err) { alert("Run failed: " + err.message); }
  };

  document.getElementById("btnAbPasteSubmit").onclick = async () => {
    if (!_abCurrentTask) return;
    const content = document.getElementById("abPasteInput").value.trim();
    if (!content) return;
    try {
      await api.agentBench.addMessage(_abCurrentTask.id, { role: "agent", content });
      document.getElementById("abPasteInput").value = "";
      await _abLoadThread(_abCurrentTask.id);
      const task = await api.agentBench.getTask(_abCurrentTask.id).catch(() => _abCurrentTask);
      _abCurrentTask = task;
      _abUpdateRunControls(task);
    } catch (err) { alert("Error: " + err.message); }
  };

  document.getElementById("btnAbViewPrompt").onclick = async () => {
    if (!_abCurrentTask) return;
    try {
      const { prompt } = await api.agentBench.getPrompt(_abCurrentTask.id);
      openModal("Agent Prompt", `
        <pre style="font-size:11px;white-space:pre-wrap;word-break:break-word;max-height:450px;overflow:auto;line-height:1.5">${prompt}</pre>
      `, [
        { label: "Copy to Clipboard", cls: "btn btn-primary", action: () => {
          navigator.clipboard?.writeText(prompt).then(() => {
            const b = document.querySelector("#modalFooter .btn-primary");
            if (b) { const orig = b.textContent; b.textContent = "Copied!"; setTimeout(() => b.textContent = orig, 1500); }
          }).catch(() => {});
        }},
        { label: "Close", cls: "btn btn-secondary", action: closeModal },
      ]);
    } catch (err) { alert("Error: " + err.message); }
  };

  // Copy Prompt button — available in the paste panel for quick access
  document.getElementById("btnAbCopyPrompt").onclick = async () => {
    if (!_abCurrentTask) return;
    const btn = document.getElementById("btnAbCopyPrompt");
    try {
      const { prompt } = await api.agentBench.getPrompt(_abCurrentTask.id);
      await navigator.clipboard.writeText(prompt);
      if (btn) { const orig = btn.textContent; btn.textContent = "Copied!"; setTimeout(() => btn.textContent = orig, 1500); }
    } catch (err) { alert("Could not copy: " + err.message); }
  };

  document.getElementById("btnAbViewDiff").onclick = async () => {
    if (!_abCurrentTask) return;
    try {
      const { diffs, note } = await api.agentBench.getDiff(_abCurrentTask.id);
      if (!diffs.length) {
        const msg = note
          ? `<div class="empty-state" style="font-size:13px;line-height:1.6">${note}</div>`
          : '<div class="empty-state">No file changes recorded for the latest run.</div>';
        openModal("Diff", msg, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
        return;
      }
      const html = diffs.map(d => {
        const lines = d.diff.split("\n").map(line => {
          const cls = line.startsWith("+") && !line.startsWith("+++") ? "add"
                    : line.startsWith("-") && !line.startsWith("---") ? "del"
                    : line.startsWith("@@") ? "hdr" : "ctx";
          return `<div class="ab-diff-line ${cls}">${line.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>`;
        }).join("");
        return `<div class="ab-diff-file">
          <div class="ab-diff-file-header">
            <span class="ab-diff-status-${d.status}">${d.status.toUpperCase()}</span>
            <span>${d.path}</span>
          </div>
          <div class="ab-diff-content">${lines}</div>
        </div>`;
      }).join("");
      openModal(`Diff — ${diffs.length} file(s) changed`,
        `<div style="max-height:500px;overflow-y:auto">${html}</div>`,
        [{ label: "Close", cls: "btn btn-secondary", action: closeModal }],
      );
    } catch (err) { alert("Error: " + err.message); }
  };

  const _abDoReview = async (decision) => {
    if (!_abCurrentTask) return;
    const notes = document.getElementById("abReviewNotes").value.trim();
    try {
      await api.agentBench.review(_abCurrentTask.id, { decision, notes: notes || null });
      document.getElementById("abReviewNotes").value = "";
      const task = await api.agentBench.getTask(_abCurrentTask.id).catch(() => _abCurrentTask);
      _abCurrentTask = task;
      const statusEl = document.getElementById("abDetailStatus");
      if (statusEl) { statusEl.className = _abStatusClass(task.status); statusEl.textContent = _abStatusLabel(task.status); }
      _abUpdateRunControls(task);

      // After approval of a firmware or port-to-hub task, show build + OTA guidance
      if (decision === "approved" && ["firmware-feature", "port-to-hub", "bug-fix"].includes(task.template)) {
        _showNextStepsFirmware(task);
      }
    } catch (err) { alert("Error: " + err.message); }
  };

  function _showNextStepsFirmware(task) {
    openModal("Changes Approved — Next Steps", `
      <div class="ab-next-steps">
        <h4>✓ Agent changes approved. Here's how to get firmware onto your device:</h4>
        <ol>
          <li><strong>Build the firmware</strong> — open the project's <code>firmware/</code> folder in a terminal and run:<br>
            <code>pio run -e esp32dev</code><br>
            The compiled binary will be at <code>.pio/build/&lt;env&gt;/firmware.bin</code>.</li>
          <li><strong>Upload to the hub catalog</strong> — go to <strong>OTA / Firmware → + Upload Firmware</strong>, select the <code>.bin</code> file, set the board and version, choose channel <em>dev</em>.</li>
          <li><strong>Push to device</strong> — click <strong>Push to Device</strong> on the catalog entry and select your paired ESP32. The hub sends the binary over WiFi.</li>
          <li><strong>Monitor</strong> — watch Serial output (<code>pio device monitor</code>) to confirm the new firmware boots and behaves as expected.</li>
        </ol>
        <p style="margin-top:10px;font-size:12px;color:var(--color-text-muted)">
          PlatformIO not installed? Run <strong>Agent Bench → Doctor → Install</strong> to add it from the portal.
        </p>
      </div>
    `, [
      { label: "Go to OTA", cls: "btn btn-primary", action: () => { closeModal(); showView("ota"); } },
      { label: "Close", cls: "btn btn-secondary", action: closeModal },
    ]);
  }

  document.getElementById("btnAbApprove").onclick  = () => _abDoReview("approved");
  document.getElementById("btnAbChanges").onclick  = () => _abDoReview("needs_changes");
  document.getElementById("btnAbReject").onclick   = () => _abDoReview("rejected");

  // Filter buttons
  document.getElementById("abFilterRow").addEventListener("click", async (e) => {
    const btn = e.target.closest(".ab-filter");
    if (!btn) return;
    _abStatusFilter = btn.dataset.status;
    document.querySelectorAll(".ab-filter").forEach(b => b.classList.toggle("active", b === btn));
    await _abLoadTaskList();
  });
}

// ── View router ────────────────────────────────────────────────────────────

const viewLoaders = {
  fleet:         loadFleet,
  projects:      loadProjects,
  recipes:       loadRecipes,
  workers:       loadWorkers,
  cards:         loadCards,
  jobs:          loadJobs,
  ota:           loadOTA,
  design:        loadDesign,
  events:        loadEvents,
  rules:         loadRules,
  "agent-bench": loadAgentBench,
};

function loadView(name) {
  const loader = viewLoaders[name];
  if (loader) loader().catch(err => console.error(`Load ${name}:`, err));
}

// ── Modal helpers ──────────────────────────────────────────────────────────

const overlay   = document.getElementById("modalOverlay");
const modalTitle = document.getElementById("modalTitle");
const modalBody  = document.getElementById("modalBody");
const modalFooter = document.getElementById("modalFooter");

function openModal(title, bodyHTML, buttons = []) {
  modalTitle.textContent  = title;
  modalBody.innerHTML     = bodyHTML;
  modalFooter.innerHTML   = "";
  for (const btn of buttons) {
    const b = el("button", btn.cls, btn.label);
    b.onclick = btn.action;
    modalFooter.appendChild(b);
  }
  overlay.classList.remove("hidden");
}

function closeModal() {
  overlay.classList.add("hidden");
  modalBody.innerHTML = "";
  modalFooter.innerHTML = "";
}

document.getElementById("modalClose").onclick = closeModal;
overlay.addEventListener("click", e => { if (e.target === overlay) closeModal(); });

// ── Browser push notifications + WebSocket realtime stream ────────────────

const _NOTIF_KEY  = "espai_notif_enabled";
const _NOTIF_ICON = "/static/img/logo-192.png";  // fallback gracefully if absent

let _ws           = null;
let _wsRetryTimer = null;

function _notifEnabled() {
  return localStorage.getItem(_NOTIF_KEY) === "1";
}

async function _requestNotifPermission() {
  if (!("Notification" in window)) return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  const result = await Notification.requestPermission();
  return result === "granted";
}

function _showNotif(title, body) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const n = new Notification(title, { body, icon: _NOTIF_ICON, tag: "espai-event" });
    setTimeout(() => n.close(), 6000);
  } catch (_) {}
}

function _handleLiveEvent(ev) {
  if (_notifEnabled()) {
    const src  = ev.source     || "system";
    const type = ev.event_type || "event";
    _showNotif(`ESPAI — ${type}`, `From: ${src}`);
  }
  // Live-refresh events view if open
  const active = document.querySelector(".view.active");
  if (active?.id === "view-events") loadEvents();
}

function _connectWS() {
  if (_ws && _ws.readyState < 2) return;  // OPEN(1) or CONNECTING(0)
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  _ws = new WebSocket(`${proto}//${location.host}/api/ws`);

  _ws.onopen = () => {
    if (_wsRetryTimer) { clearTimeout(_wsRetryTimer); _wsRetryTimer = null; }
  };

  _ws.onmessage = (e) => {
    try { _handleLiveEvent(JSON.parse(e.data)); } catch (_) {}
  };

  _ws.onerror = () => {};

  _ws.onclose = () => {
    _ws = null;
    // Retry after 5 s; back-off guard: don't pile up timers
    if (!_wsRetryTimer) _wsRetryTimer = setTimeout(() => { _wsRetryTimer = null; _connectWS(); }, 5000);
  };
}

async function _toggleNotifications() {
  const btn = document.getElementById("btnNotif");
  if (_notifEnabled()) {
    localStorage.removeItem(_NOTIF_KEY);
    if (btn) { btn.dataset.tip = "Enable browser notifications for live events"; btn.classList.remove("notif-on"); }
  } else {
    const ok = await _requestNotifPermission();
    if (!ok) {
      alert("Notifications blocked — allow them in browser settings, then try again.");
      return;
    }
    localStorage.setItem(_NOTIF_KEY, "1");
    if (btn) { btn.dataset.tip = "Disable browser notifications"; btn.classList.add("notif-on"); }
  }
}

// ── Boot ───────────────────────────────────────────────────────────────────

(async function boot() {
  await loadTokens();
  checkHubStatus();
  setInterval(checkHubStatus, 30_000);
  _abWireEvents();

  // Mobile sidebar toggle
  const sidebar   = document.getElementById("sidebar");
  const hamburger = document.getElementById("btnHamburger");
  const overlay_  = document.getElementById("sidebarOverlay");
  function closeSidebar() { sidebar.classList.remove("open"); if (overlay_) overlay_.classList.remove("active"); }
  function openSidebar()  { sidebar.classList.add("open");    if (overlay_) overlay_.classList.add("active"); }
  hamburger?.addEventListener("click", () => sidebar.classList.contains("open") ? closeSidebar() : openSidebar());
  overlay_?.addEventListener("click", closeSidebar);
  navItems.forEach(item => item.addEventListener("click", () => { if (window.innerWidth < 700) closeSidebar(); }));

  showView("fleet");
  setInterval(() => {
    const active = document.querySelector(".view.active");
    if (active && active.id === "view-fleet") loadFleet();
  }, 60_000);

  // WebSocket is always connected (instant event fan-out + live events view refresh)
  // Desktop notifications only fire when the user has opted in via the bell button
  _connectWS();

  const btn = document.getElementById("btnNotif");
  if (btn) {
    btn.onclick = _toggleNotifications;
    if (_notifEnabled()) {
      btn.dataset.tip = "Disable browser notifications";
      btn.classList.add("notif-on");
    } else {
      btn.dataset.tip = "Enable browser notifications for live events";
    }
  }
})();
