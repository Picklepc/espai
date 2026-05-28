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
    card.innerHTML = `
      <span class="${dotClass}"></span>
      <div class="device-info">
        <div class="device-name">${d.name || d.id}</div>
        <div class="device-meta">${d.ip || "no IP"} · ${d.board || "unknown board"} · fw ${d.fw_version || "?"} · ${timeAgo(d.last_seen)}</div>
      </div>
      <span class="device-badge ${d.paired ? "" : "unpaired"}">${d.paired ? "Paired" : "Unpaired"}</span>
    `;
    const actions = el("div", "device-actions");
    if (!d.paired) {
      const pairBtn = el("button", "btn btn-secondary btn-sm");
      pairBtn.textContent = "Pair";
      pairBtn.onclick = () => pairDevice(d.id);
      actions.appendChild(pairBtn);
    }
    const delBtn = el("button", "btn btn-danger btn-sm");
    delBtn.innerHTML = "&#x2715;";
    delBtn.title = "Remove from fleet";
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
    <div class="form-field">
      <label>IP Address</label>
      <input type="text" id="newDeviceIP" placeholder="192.168.1.100">
    </div>
    <div class="form-field">
      <label>Name (optional)</label>
      <input type="text" id="newDeviceName" placeholder="My Node">
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
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:12px">
      Paste backup JSON below. Only <b>devices</b>, <b>projects</b>, and <b>rules</b> will be restored.
      Events, jobs, and OTA log are never overwritten.
    </p>
    <div class="form-field">
      <textarea id="restoreJson" rows="10" style="font-family:monospace;font-size:11px" placeholder='{"devices":[...],"projects":[...],"rules":[],...}'></textarea>
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
    <div class="form-field">
      <label>Firmware .bin file</label>
      <input type="file" id="fwFile" accept=".bin">
    </div>
    <div class="form-field">
      <label>Board</label>
      <input type="text" id="fwBoard" placeholder="esp32dev" value="esp32dev">
    </div>
    <div class="form-field">
      <label>Version</label>
      <input type="text" id="fwVersion" placeholder="1.0.0" value="1.0.0">
    </div>
    <div class="form-field">
      <label>Channel</label>
      <select id="fwChannel">
        <option value="dev">dev</option>
        <option value="beta">beta</option>
        <option value="stable">stable</option>
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

async function refreshProjectFiles(projectId, silent = false) {
  const fileList  = document.getElementById("projFileList");
  const statusEl  = document.getElementById("projFilesStatus");
  if (!silent) fileList.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const { files } = await api.projects.files(projectId);
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

document.getElementById("btnProjBack").onclick = () => {
  _currentProject = null;
  _stopFilesPoller();
  _clearProjectTheme();
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
    <div class="form-field">
      <label>Name</label>
      <input type="text" id="newProjName" placeholder="My Project">
    </div>
    <div class="form-field">
      <label>Description (optional)</label>
      <textarea id="newProjDesc" rows="3" placeholder="What does this project do?"></textarea>
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
        <span class="tag" title="filesystem permission" style="opacity:.7">fs:${fs}</span>
        <span class="tag" title="network permission"    style="opacity:.7">net:${net}</span>
        ${item.quarantine ? '<span class="tag" style="color:var(--color-warning)">quarantined</span>' : ""}
      </div>
    `;
    const testBtn = el("button", "btn btn-secondary btn-sm", "▶ Test");
    testBtn.style.marginTop = "10px";
    testBtn.onclick = () => openWorkerTestModal(item);
    card.appendChild(testBtn);
    el_.appendChild(card);
  }
}

function openWorkerTestModal(worker) {
  const wname = worker.name || worker._folder;
  openModal(`Test Worker — ${worker.display_name || wname}`, `
    <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:10px">
      Inputs JSON (or leave as <code>{}</code> for no inputs):
    </p>
    <div class="form-field">
      <textarea id="workerTestInputs" rows="5" style="font-family:monospace;font-size:12px">{}</textarea>
    </div>
    <div style="display:flex;align-items:center;gap:10px;margin-top:6px">
      <label style="font-size:12px">Timeout (s)</label>
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
      return `<span class="tag" style="font-size:10px;color:${color}">${k}:${val}</span>`;
    }).join("");
    const rtSafe = cost.realtime_safe === false
      ? '<span class="tag" style="font-size:10px;color:var(--color-warning)">not-rt-safe</span>' : "";

    row.innerHTML = `
      <span class="job-status ${j.status}">${j.status}</span>
      <span style="font-weight:600;font-size:13px">${j.worker_name}</span>
      <span style="display:flex;gap:4px;align-items:center">${costTags}${rtSafe}</span>
      <span style="color:var(--color-text-muted);font-size:12px;flex:1">${j.id.slice(0,8)}</span>
      <span style="color:var(--color-text-muted);font-size:12px">${timeAgo(j.created)}</span>
    `;
    // Click to show outputs
    if (j.outputs || j.error) {
      row.style.cursor = "pointer";
      row.title = "Click for details";
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
          <span class="tag">${fw.sha256 ? fw.sha256.slice(0,12) + "…" : "no checksum"}</span>
          <span class="tag">${timeAgo(fw.uploaded)}</span>
          ${goodBadge}${rbBadge}
        </div>
      `;
      const btnRow = el("div", "");
      btnRow.style.cssText = "display:flex;gap:6px;margin-top:10px;flex-wrap:wrap";

      const pushBtn = el("button", "btn btn-secondary btn-sm", "Push to Device");
      pushBtn.onclick = () => openPushModal(fw);
      btnRow.appendChild(pushBtn);

      if (!fw.known_good) {
        const goodBtn = el("button", "btn btn-secondary btn-sm", "✓ Mark Known Good");
        goodBtn.onclick = async () => {
          try {
            await api.ota.markGood(fw._folder || `${fw.board}-${fw.version}`);
            loadOTA();
          } catch (err) { alert("Error: " + err.message); }
        };
        btnRow.appendChild(goodBtn);
      }

      const rbBtn = el("button", "btn btn-secondary btn-sm", "↩ Set Rollback");
      rbBtn.onclick = () => openRollbackTargetModal(fw, catalog);
      btnRow.appendChild(rbBtn);

      const rolloutBtn = el("button", "btn btn-secondary btn-sm", "⟳ Staged Rollout");
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
      <label>Target Device</label>
      <select id="pushDeviceSel">${opts}</select>
    </div>
    <div id="boardCompatWarn" class="compat-warning hidden">
      &#9888; Board mismatch: firmware is for <strong>${fw.board}</strong> but selected device reports a different board.
      <label style="display:block;margin-top:6px">
        <input type="checkbox" id="pushForce"> Override anyway (may brick device)
      </label>
    </div>
    <div class="form-field">
      <label>Operator</label>
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
      <div class="rule-enabled-dot ${r.enabled ? "on" : "off"}"></div>
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
    toggleBtn.onclick = async () => {
      await api.rules.update(r.id, { enabled: !r.enabled }).catch(() => {});
      loadRules();
    };
    const delBtn = el("button", "btn btn-danger btn-sm");
    delBtn.innerHTML = "&#x2715;";
    delBtn.title = "Delete rule";
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
    <div class="form-field">
      <label>Rule Name</label>
      <input type="text" id="ruleNameInput" placeholder="Alert on checkin">
    </div>
    <div class="form-field">
      <label>Trigger Event Type</label>
      <input type="text" id="ruleEventType" placeholder="device.checkin">
    </div>
    <div class="form-field">
      <label>Source Filter (optional — leave blank for any)</label>
      <input type="text" id="ruleSourceFilter" placeholder="my-node-id">
    </div>
    <div class="form-field">
      <label>Action</label>
      <select id="ruleActionType">
        <option value="log_event">Log Event (no side effects)</option>
        <option value="run_worker">Run Worker</option>
        <option value="webhook">Webhook POST</option>
        <option value="theme_change">Theme Token Override</option>
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
  };
  return labels[status] || status;
}

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
    card.innerHTML = `
      <div class="ab-task-info">
        <div class="ab-task-title">${t.title}</div>
        <div class="ab-task-meta">${t.template} · ${t.lane} lane · ${timeAgo(t.updated)}</div>
      </div>
      <span class="${_abStatusClass(t.status)}">${_abStatusLabel(t.status)}</span>
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
    <span>Template: <strong>${task.template}</strong></span>
    <span>Lane: <strong>${task.lane}</strong></span>
    ${task.adapter_id ? `<span>Adapter: <strong>${task.adapter_id}</strong></span>` : ""}
    ${allowed.length ? `<span>Paths: <strong>${allowed.length}</strong></span>` : ""}
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
    div.textContent = m.role === "system" ? "[PROMPT — scroll to view]" : m.content.slice(0, 2000) + (m.content.length > 2000 ? "\n…(truncated)" : "");
    if (m.role === "system") {
      div.title = m.content;
      div.style.cursor = "pointer";
      div.onclick = () => openModal("Agent Prompt", `<pre style="font-size:11px;white-space:pre-wrap;word-break:break-word;max-height:400px;overflow:auto">${m.content}</pre>`,
        [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    }
    div.appendChild(ts);
    threadEl.appendChild(div);
  }
  threadEl.scrollTop = threadEl.scrollHeight;
}

async function _abSetupAdapterSelect() {
  const sel = document.getElementById("abAdapterSelect");
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
    opt.textContent = a.display_name + (a.installed === false ? " (not installed)" : "");
    if (a.installed === false) opt.disabled = true;
    sel.appendChild(opt);
  }
  if (_abCurrentTask?.adapter_id) sel.value = _abCurrentTask.adapter_id;
}

function _abUpdateRunControls(task) {
  const runPanel   = document.getElementById("abRunPanel");
  const pastePanel = document.getElementById("abPastePanel");
  const reviewPanel = document.getElementById("abReviewPanel");

  const canRun    = ["draft", "needs_changes"].includes(task.status);
  const needsPaste = task.status === "awaiting_review" && task.latest_run?.status === "awaiting_input";
  const needsReview = ["awaiting_review"].includes(task.status);

  runPanel.style.display = canRun ? "" : "none";
  pastePanel.classList.toggle("hidden", !needsPaste);
  reviewPanel.classList.toggle("hidden", !needsReview);
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

  document.getElementById("btnAbNewTask").onclick = async () => {
    let projects = [];
    try { projects = await api.projects.list(); } catch (_) {}
    const projOpts = [
      '<option value="">— no project —</option>',
      ...projects.map(p => `<option value="${p.id}">${p.name}</option>`),
    ].join("");
    openModal("New Agent Task", `
      <div class="form-field">
        <label>Title</label>
        <input type="text" id="abNewTitle" placeholder="Add motion detection to firmware">
      </div>
      <div class="form-field">
        <label>Description</label>
        <textarea id="abNewDesc" rows="4" placeholder="Describe what the agent should build or fix…"></textarea>
      </div>
      <div class="form-field">
        <label>Template</label>
        <select id="abNewTemplate">
          <option value="custom">custom</option>
          <option value="firmware-feature">firmware-feature</option>
          <option value="hub-feature">hub-feature</option>
          <option value="recipe-feature">recipe-feature</option>
          <option value="bug-fix">bug-fix</option>
        </select>
      </div>
      <div class="form-field">
        <label>Project (optional)</label>
        <select id="abNewProject">${projOpts}</select>
      </div>
      <div class="form-field">
        <label>Acceptance criteria (one per line)</label>
        <textarea id="abNewCriteria" rows="3" placeholder="- Builds without error&#10;- LED blinks correctly"></textarea>
      </div>
      <div class="form-field">
        <label>Allowed paths (one per line)</label>
        <textarea id="abNewPaths" rows="2" placeholder="firmware/seed/src&#10;hub/backend/routers"></textarea>
      </div>
    `, [
      { label: "Create Task", cls: "btn btn-primary", action: async () => {
        const title = document.getElementById("abNewTitle").value.trim();
        const desc  = document.getElementById("abNewDesc").value.trim();
        if (!title || !desc) return;
        const template   = document.getElementById("abNewTemplate").value;
        const project_id = document.getElementById("abNewProject").value || null;
        const criteriaRaw = document.getElementById("abNewCriteria").value.trim();
        const pathsRaw    = document.getElementById("abNewPaths").value.trim();
        const acceptance_criteria = criteriaRaw ? criteriaRaw.split("\n").map(s => s.trim().replace(/^[-*]\s*/, "")).filter(Boolean) : [];
        const allowed_paths       = pathsRaw ? pathsRaw.split("\n").map(s => s.trim()).filter(Boolean) : [];
        try {
          await api.agentBench.createTask({ title, description: desc, template, project_id, acceptance_criteria, allowed_paths });
          closeModal();
          _abLoadTaskList();
        } catch (err) { alert("Error: " + err.message); }
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
  };

  document.getElementById("btnAbDoctor").onclick = async () => {
    const d = await api.agentBench.doctor().catch(err => ({ error: err.message }));
    if (d.error) { openModal("Doctor", `<p class="empty-state">${d.error}</p>`, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]); return; }
    const toolRows = Object.entries(d.tools || {}).map(([name, info]) => {
      const ok = info.found;
      return `<div class="doctor-row">
        <span class="doctor-icon ${ok ? "ok" : "miss"}">${ok ? "✓" : "—"}</span>
        <span class="doctor-name">${name}</span>
        <span class="doctor-val">${info.version || (ok ? "found" : "not found")}</span>
      </div>`;
    }).join("");
    const adapterRows = Object.entries(d.adapters_ready || {}).map(([k, v]) => {
      return `<div class="doctor-row">
        <span class="doctor-icon ${v ? "ok" : "miss"}">${v ? "✓" : "✗"}</span>
        <span class="doctor-name">${k}</span>
        <span class="doctor-val" style="color:${v ? "var(--color-success)" : "var(--color-danger)"}">${v ? "ready" : "not installed"}</span>
      </div>`;
    }).join("");
    openModal("Agent Bench Doctor", `
      <p class="doctor-section-label">Tools</p>
      ${toolRows}
      <p class="doctor-section-label" style="margin-top:14px">Adapters</p>
      ${adapterRows}
    `, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
  };

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
      `, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    } catch (err) { alert("Error: " + err.message); }
  };

  document.getElementById("btnAbViewDiff").onclick = async () => {
    if (!_abCurrentTask) return;
    try {
      const { diffs } = await api.agentBench.getDiff(_abCurrentTask.id);
      if (!diffs.length) {
        openModal("No Changes", '<div class="empty-state">No file changes recorded for the latest run.</div>',
          [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
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
    } catch (err) { alert("Error: " + err.message); }
  };

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
    if (btn) { btn.title = "Enable notifications"; btn.classList.remove("notif-on"); }
  } else {
    const ok = await _requestNotifPermission();
    if (!ok) {
      alert("Notifications blocked — allow them in browser settings, then try again.");
      return;
    }
    localStorage.setItem(_NOTIF_KEY, "1");
    if (btn) { btn.title = "Disable notifications"; btn.classList.add("notif-on"); }
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
      btn.title = "Disable notifications";
      btn.classList.add("notif-on");
    } else {
      btn.title = "Enable notifications";
    }
  }
})();
