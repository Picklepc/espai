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
  // Reset registry detail views when navigating away
  for (const t of ["worker", "card", "recipe"]) {
    if (name !== `${t}s`) {
      document.getElementById(`${t}-detail-view`)?.classList.add("hidden");
      document.getElementById(`${t}-list-view`)?.classList.remove("hidden");
    }
  }
  if (name !== "workers" && name !== "cards" && name !== "recipes") {
    _regEditorCtx = null;
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

// ── Home / Dashboard view ──────────────────────────────────────────────────

async function loadHome() {
  const grid = document.getElementById("homeProjGrid");
  if (!grid) return;
  grid.innerHTML = '<div class="empty-state">Loading…</div>';

  const [projects, devices, jobs] = await Promise.all([
    api.projects.list().catch(() => []),
    api.devices.list().catch(() => []),
    api.jobs.list("running").catch(() => []),
  ]);

  // Stats
  const online     = devices.filter(d => isOnline(d.last_seen)).length;
  const paired     = devices.filter(d => d.paired).length;
  const activeJobs = (jobs || []).length;
  document.getElementById("hstatOnline").textContent   = online;
  document.getElementById("hstatPaired").textContent   = paired;
  document.getElementById("hstatTotal").textContent    = devices.length;
  document.getElementById("hstatProjects").textContent = projects.length;
  document.getElementById("hstatJobs").textContent     = activeJobs;

  // Local Network categorized grid (loads independently)
  loadLocalNetwork();

  // Build device → [project + role] map from the nodes lists
  const devProjectMap = new Map();
  for (const p of projects) {
    const nodes = Array.isArray(p.nodes) ? p.nodes : (Array.isArray(p.devices) ? p.devices.map(id => ({ device_id: id, role: "node" })) : []);
    for (const n of nodes) {
      if (!devProjectMap.has(n.device_id)) devProjectMap.set(n.device_id, []);
      devProjectMap.get(n.device_id).push({ name: p.name, id: p.id, role: n.role || "node" });
    }
  }

  // Device list — pill style for the dashboard
  const devListEl = document.getElementById("homeDeviceList");
  if (devListEl) _renderDevicePills(devListEl, devices, loadHome, devProjectMap);

  if (!projects.length) {
    grid.innerHTML = '<div class="empty-state">No projects yet — click <strong>+ New Project</strong> to create your first one.</div>';
    return;
  }

  // Render project cards — no iframes, no N+1 API calls, instant.
  // "Open App" links to /app/{slug}/ directly; hub serves the web app or a 404 page.
  grid.innerHTML = "";
  const devMap = new Map(devices.map(d => [d.id, d]));
  projects.forEach(p => {
    const slug      = p.slug || p.name;
    const appUrl    = `/app/${encodeURIComponent(slug)}/`;
    const linkedIds = Array.isArray(p.devices) ? p.devices : [];
    const onlineLinked = linkedIds.filter(id => {
      const d = devMap.get(id);
      return d && isOnline(d.last_seen);
    }).length;
    const deviceBadge = linkedIds.length
      ? `<span class="tag" data-tip="${onlineLinked}/${linkedIds.length} linked device(s) online"
             style="${onlineLinked ? "color:var(--color-success)" : ""}">${onlineLinked}/${linkedIds.length} online</span>`
      : `<span class="tag" style="opacity:.5" data-tip="No devices linked yet">no devices</span>`;

    // Deterministic color from project name
    let hash = 0;
    for (const c of p.name) hash = (hash * 31 + c.charCodeAt(0)) & 0xffffffff;
    const hue  = Math.abs(hash) % 360;
    const bg   = `hsl(${hue},40%,22%)`;
    const accent = `hsl(${hue},60%,50%)`;

    // Node count — use structured nodes if available, fallback to devices array
    const nodes      = Array.isArray(p.nodes) ? p.nodes : linkedIds.map(id => ({ device_id: id, role: "node" }));
    const nodeCount  = nodes.length;
    const topology   = p.meta?.topology || "standalone";
    const appType    = p.meta?.app_type || "firmware";
    const topoIcon   = _TOPOLOGY_ICONS?.[topology] || "◎";
    const topoLabel  = topology !== "standalone" ? `${topoIcon} ${topology}` : null;

    const statusLabel = onlineLinked
      ? `<span style="color:var(--color-success)">${onlineLinked}/${nodeCount} ONLINE</span>`
      : nodeCount
        ? `<span style="color:var(--color-text-muted)">${nodeCount} NODE${nodeCount > 1 ? "S" : ""} · OFFLINE</span>`
        : `<span style="color:var(--color-text-muted)">NO NODES</span>`;
    const dotColor = onlineLinked ? "var(--color-success)"
                   : nodeCount ? "var(--color-warning)" : "#546e7a";

    const card = el("div", "home-proj-card");
    card.dataset.tip = "Click Detail → to open project, or Open App to launch the web interface";
    card.innerHTML = `
      <div class="home-proj-hero" style="background:${bg}">
        <div class="home-proj-initials" style="color:${accent};text-shadow:0 0 24px ${accent}88">
          ${p.name.slice(0,2).toUpperCase()}</div>
        <div class="home-proj-slug">${slug}</div>
        ${topoLabel ? `<div style="position:absolute;top:6px;right:8px;font-family:monospace;font-size:8px;letter-spacing:.06em;color:${accent};opacity:.8">${topoLabel.toUpperCase()}</div>` : ""}
      </div>
      <div class="home-proj-status" data-tip="${onlineLinked} of ${nodeCount} nodes online · topology: ${topology} · app: ${appType}">
        <span class="home-proj-status-dot" style="background:${dotColor};box-shadow:0 0 6px ${dotColor}"></span>
        <span style="font-family:monospace;font-size:9px;letter-spacing:.08em">${statusLabel}</span>
        ${appType !== "firmware" ? `<span style="margin-left:auto;font-family:monospace;font-size:8px;color:var(--color-text-muted)">${appType === "hub" ? "HUB APP" : "HYBRID"}</span>` : ""}
      </div>
      <div class="home-proj-body">
        <div class="home-proj-name">${p.name}</div>
        <div class="home-proj-desc">${p.description || '<span style="opacity:.4;font-style:italic">no description</span>'}</div>
      </div>
      <div class="home-proj-actions">
        <a href="${appUrl}" target="_blank" class="btn btn-primary btn-sm"
           data-tip="Open ${p.name} web app in a new tab">Open App ↗</a>
        <button class="btn btn-secondary btn-sm home-goto-proj"
                data-tip="Open project detail — nodes, files, firmware, agent tasks">Detail →</button>
      </div>`;
    card.querySelector(".home-goto-proj").onclick = () => {
      showView("projects");
      setTimeout(async () => {
        const proj = await api.projects.get(p.id).catch(() => p);
        openProject(proj);
      }, 100);
    };
    grid.appendChild(card);
  });
}

// Wire Home buttons
document.getElementById("btnHomeRefresh").onclick  = loadHome;
document.getElementById("btnHomeNewProject").onclick = () => {
  showView("projects");
  setTimeout(() => document.getElementById("btnNewProject")?.click(), 150);
};

// ── Local Network service grid ──────────────────────────────────────────────

const _SVC_COLORS = {
  tasmota:"#e07828",esphome:"#00bcd4",homeassist:"#18bcf2",openwrt:"#2ecc71",
  pihole:"#e74c3c",proxmox:"#e67e22",jellyfin:"#8e44ad",plex:"#e5a00d",
  emby:"#52b54b",kodi:"#17b2e8",navidrome:"#f47225",grafana:"#f46800",
  portainer:"#13bef9",gitea:"#609926",nextcloud:"#0082c9",synology:"#b5b5b5",
  espai:"#1aafc4",unknown:"#546e7a",
};
const _SVC_EMOJIS = {
  tasmota:"💡",esphome:"⚡",homeassist:"🏠",openwrt:"🌐",pihole:"🛡️",
  proxmox:"🖥️",jellyfin:"🎬",plex:"🟡",emby:"🟢",kodi:"🎵",navidrome:"🎵",
  grafana:"📊",portainer:"🐳",gitea:"🦎",nextcloud:"☁️",synology:"💾",
  espai:"📡",unknown:"🌐",
};
const _SVC_CATEGORY_ORDER = ["projects","smart-home","media","network","tools","other"];
const _SVC_CATEGORY_LABELS = {
  "projects":"Projects","smart-home":"Smart Home","media":"Media",
  "network":"Network","tools":"Tools","other":"Other",
};

async function loadLocalNetwork() {
  const container = document.getElementById("localNetContent");
  if (!container) return;

  const services = await api.services.list().catch(() => []);

  // Outer band wrapper — always rendered so the section header appears
  const outerBand = el("div", "home-band");
  const outerHd = el("div", "home-band-hd");
  const totalVisible = services.length;
  outerHd.innerHTML = `<span class="home-band-label">Local Network</span>
    <span style="font-family:monospace;font-size:9px;color:var(--color-text-muted);letter-spacing:.06em">${totalVisible} service${totalVisible !== 1 ? "s" : ""}</span>`;
  outerBand.appendChild(outerHd);

  if (!services.length) {
    const hint = el("div", "svc-discover-hint");
    hint.innerHTML = `No services yet. Click <strong>🔍 Discover</strong> to scan your LAN, or
      <strong>+ Add Service</strong> to add Jellyfin, Home Assistant, or any local web service by hostname and port.`;
    outerBand.appendChild(hint);
    container.innerHTML = "";
    container.appendChild(outerBand);
    return;
  }

  // Group by category
  const groups = {};
  for (const svc of services) {
    const cat = svc.category || "other";
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(svc);
  }

  container.innerHTML = "";
  container.appendChild(outerBand);

  for (const cat of _SVC_CATEGORY_ORDER) {
    const items = groups[cat];
    if (!items?.length) continue;

    const band = el("div", "svc-band");
    const hd = el("div", "svc-band-hd");
    hd.innerHTML = `<span class="svc-band-label">${_SVC_CATEGORY_LABELS[cat] || cat}</span>
                    <span class="svc-band-count">${items.length}</span>`;
    band.appendChild(hd);

    const grid = el("div", "svc-grid");
    for (const svc of items) {
      grid.appendChild(_makeSvcCard(svc));
    }
    band.appendChild(grid);
    outerBand.appendChild(band);
  }
}

function _makeSvcCard(svc) {
  const color    = svc.color || _SVC_COLORS[svc.service_type] || _SVC_COLORS.unknown;
  const emoji    = _SVC_EMOJIS[svc.service_type] || "🌐";
  const label    = svc.label || svc.title || `${svc.host}:${svc.port}`;
  const addr     = svc.port === 80 ? svc.host : `${svc.host}:${svc.port}`;
  const url      = `${svc.protocol || "http"}://${svc.host}${svc.port !== 80 ? ":" + svc.port : ""}/`;
  const isPinned = svc.pinned;

  const tile = el("div", "svc-tile");
  tile.style.setProperty("--tile-color", color);
  tile.dataset.tip = `${label} · ${addr}${svc.last_seen ? " · seen " + timeAgo(svc.last_seen) : ""}`;

  // Icon bubble
  const iconEl = el("div", "svc-tile-icon");
  if (svc.favicon_url) {
    const img = document.createElement("img");
    img.src = svc.favicon_url;
    img.alt = emoji;
    img.onerror = () => { iconEl.innerHTML = `<span style="font-size:22px">${emoji}</span>`; };
    iconEl.appendChild(img);
  } else {
    iconEl.innerHTML = `<span style="font-size:22px">${emoji}</span>`;
  }
  tile.appendChild(iconEl);

  // Name + address
  const nameEl = el("div", "svc-tile-name", label);
  tile.appendChild(nameEl);
  const addrEl = el("div", "svc-tile-addr", addr);
  tile.appendChild(addrEl);

  // Buttons
  const ctrl = el("div", "svc-tile-ctrl");

  const openBtn = document.createElement("a");
  openBtn.href = url;
  openBtn.target = "_blank";
  openBtn.rel = "noopener";
  openBtn.className = "btn btn-primary btn-sm";
  openBtn.textContent = "Open ↗";
  openBtn.dataset.tip = `Open ${label} in a new tab`;
  ctrl.appendChild(openBtn);

  const moreBtn = el("button", "btn btn-secondary btn-sm", "⋯");
  moreBtn.dataset.tip = "Edit label, category, pin, or hide this service";
  moreBtn.onclick = (e) => {
    e.stopPropagation();
    _openSvcEditModal(svc);
  };
  ctrl.appendChild(moreBtn);

  tile.appendChild(ctrl);

  // Pin glyph in corner
  if (isPinned) {
    const pin = el("div", "");
    pin.style.cssText = "position:absolute;top:5px;right:7px;font-size:10px;opacity:.7";
    pin.textContent = "📌";
    tile.appendChild(pin);
  }

  if (svc.is_espai && svc.project_id) {
    tile.style.cursor = "pointer";
    tile.ondblclick = () => {
      showView("projects");
      setTimeout(async () => {
        const proj = await api.projects.get(svc.project_id).catch(() => null);
        if (proj) openProject(proj);
      }, 100);
    };
  }

  return tile;
}

function _openSvcEditModal(svc) {
  const currentLabel = svc.label || svc.title || "";
  const catOpts = Object.entries(_SVC_CATEGORY_LABELS).map(([k, v]) =>
    `<option value="${k}" ${svc.category === k ? "selected" : ""}>${v}</option>`
  ).join("");

  openModal(`Edit — ${currentLabel || svc.host}`, `
    <div class="form-field">
      <label data-tip="Friendly name shown on the card — overrides the page title">Label</label>
      <input type="text" id="svcEditLabel" value="${currentLabel}" placeholder="e.g. Living Room Tasmota">
    </div>
    <div class="form-field">
      <label data-tip="Group this service with similar services on the dashboard">Category</label>
      <select id="svcEditCat">${catOpts}</select>
    </div>
  `, [
    { label: "Save", cls: "btn btn-primary", action: async () => {
      const label    = document.getElementById("svcEditLabel").value.trim() || null;
      const category = document.getElementById("svcEditCat").value;
      await api.services.update(svc.id, { label, category }).catch(err => alert(err.message));
      closeModal();
      loadLocalNetwork();
    }},
    { label: svc.pinned ? "Unpin" : "📌 Pin", cls: "btn btn-secondary", action: async () => {
      await api.services.update(svc.id, { pinned: !svc.pinned }).catch(() => {});
      closeModal();
      loadLocalNetwork();
    }},
    { label: "Hide", cls: "btn btn-secondary", action: async () => {
      if (!confirm(`Hide "${currentLabel || svc.host}"?`)) return;
      await api.services.update(svc.id, { hidden: true }).catch(() => {});
      closeModal();
      loadLocalNetwork();
    }},
    { label: "Delete Entry", cls: "btn btn-danger", action: async () => {
      if (!confirm(`Remove "${currentLabel || svc.host}" from the grid entirely?`)) return;
      await api.services.delete(svc.id).catch(() => {});
      closeModal();
      loadLocalNetwork();
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
  setTimeout(() => { const el = document.getElementById("svcEditLabel"); el?.focus(); el?.select(); }, 100);
}

// ── Discover + Add Service button handlers ──────────────────────────────────

document.getElementById("btnHomeDiscover").onclick = async () => {
  const btn = document.getElementById("btnHomeDiscover");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Scanning…";
  try {
    const result = await api.services.discover();
    loadLocalNetwork();
    btn.textContent = `✓ ${result.found} found`;
    setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000);
  } catch (err) {
    alert("Discover failed: " + err.message);
    btn.textContent = orig;
    btn.disabled = false;
  }
};

document.getElementById("btnHomeAddService").onclick = () => {
  const catOpts = Object.entries(_SVC_CATEGORY_LABELS).map(([k, v]) =>
    `<option value="${k}">${v}</option>`
  ).join("");
  openModal("Add Local Service", `
    <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:14px;line-height:1.6">
      Enter a hostname, IP address, or IP:port. The hub will probe it immediately to
      fetch its name and icon — works for Jellyfin, Home Assistant, Pi-hole, Tasmota,
      or any local web service.
    </p>
    <div class="form-field">
      <label data-tip="Hostname or IP address — e.g. jellyfin.local, 192.168.1.50">Host / IP</label>
      <input type="text" id="svcAddHost" placeholder="jellyfin.local or 192.168.1.50" style="font-family:monospace">
    </div>
    <div class="form-field">
      <label data-tip="Port number — 80 for standard HTTP (default), 8096 for Jellyfin, 8123 for Home Assistant, 3000 for Grafana">Port</label>
      <input type="number" id="svcAddPort" value="80" min="1" max="65535">
    </div>
    <div class="form-field">
      <label data-tip="Optional — overrides the page title shown on the card. Leave blank to use the auto-detected title.">Label (optional)</label>
      <input type="text" id="svcAddLabel" placeholder="e.g. My Jellyfin Server">
    </div>
    <div class="form-field">
      <label data-tip="Choose the category for this service on the dashboard">Category</label>
      <select id="svcAddCat">${catOpts}</select>
    </div>
    <p id="svcAddStatus" style="font-size:12px;color:var(--color-text-muted);min-height:18px;margin-top:4px"></p>
  `, [
    { label: "Add", cls: "btn btn-primary", action: async () => {
      const host     = document.getElementById("svcAddHost")?.value.trim();
      const port     = parseInt(document.getElementById("svcAddPort")?.value, 10) || 80;
      const label    = document.getElementById("svcAddLabel")?.value.trim() || undefined;
      const category = document.getElementById("svcAddCat")?.value;
      const status   = document.getElementById("svcAddStatus");
      if (!host) { if (status) status.textContent = "Enter a host or IP address."; return; }
      if (status) status.textContent = "Probing…";
      try {
        const svc = await api.services.add({ host, port, label, category });
        closeModal();
        loadLocalNetwork();
      } catch (err) { if (status) status.textContent = "Error: " + err.message; }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
  setTimeout(() => document.getElementById("svcAddHost")?.focus(), 100);
};

// ── Home dashboard device pills ──────────────────────────────────────────────
function _renderDevicePills(listEl, devices, onRefresh, devProjectMap = new Map()) {
  if (!devices.length) {
    listEl.innerHTML = '<div class="empty-state">No devices found. Use Scan LAN or + Add Device to discover nodes.</div>';
    return;
  }
  listEl.innerHTML = "";
  for (const d of devices) {
    const online_ = isOnline(d.last_seen);
    const pillColor = online_ ? "var(--color-success)" : d.paired ? "var(--color-warning)" : "#546e7a";
    const statusTxt = online_ ? "ONLINE" : d.paired ? "OFFLINE" : "UNREGISTERED";
    const badgeCls  = online_ ? "online" : d.paired ? "paired" : "unpaired";
    const glyph     = online_ ? "◉" : d.paired ? "◎" : "○";
    const projMemberships = devProjectMap.get(d.id) || [];

    const pill = el("div", "device-pill");
    pill.style.setProperty("--pill-color", pillColor);

    const glyphEl = el("div", "device-pill-glyph", glyph);
    const infoEl  = el("div", "device-pill-info");
    const nameEl  = el("div", "device-pill-name", d.name || d.id);
    const metaEl  = el("div", "device-pill-meta",
      `${d.ip || "no IP"} · ${d.board || "?"} · fw ${d.fw_version || "?"} · ${timeAgo(d.last_seen)}`);
    infoEl.appendChild(nameEl);
    infoEl.appendChild(metaEl);

    // Project membership chips
    if (projMemberships.length) {
      const projEl = el("div", "");
      projEl.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;margin-top:4px";
      for (const m of projMemberships.slice(0, 4)) {
        const chip = el("span", `node-role node-role-${m.role}`);
        chip.textContent = m.name;
        chip.dataset.tip = `Node in "${m.name}" as ${m.role}`;
        chip.style.cursor = "pointer";
        chip.onclick = () => {
          showView("projects");
          setTimeout(async () => {
            const proj = await api.projects.get(m.id).catch(() => null);
            if (proj) openProject(proj);
          }, 100);
        };
        projEl.appendChild(chip);
      }
      if (projMemberships.length > 4) {
        const more = el("span", "node-role node-role-node", `+${projMemberships.length - 4}`);
        more.dataset.tip = `${projMemberships.length - 4} more projects`;
        projEl.appendChild(more);
      }
      infoEl.appendChild(projEl);
    }

    const badge = el("span", `device-pill-badge ${badgeCls}`, statusTxt);
    badge.dataset.tip = online_ ? "Seen within 2 minutes"
                      : d.paired ? `Last seen ${timeAgo(d.last_seen)}`
                      : "Not paired — click Pair to register";

    const actionsEl = el("div", "device-pill-actions");
    if (!d.paired) {
      const pairBtn = el("button", "btn btn-secondary btn-sm", "Pair");
      pairBtn.dataset.tip = "Pair this device with the hub to enable OTA and trusted commands";
      pairBtn.onclick = () => pairDevice(d.id);
      actionsEl.appendChild(pairBtn);
    } else {
      const flashBtn = el("button", "btn btn-secondary btn-sm", "⬆ Flash");
      flashBtn.dataset.tip = "Push firmware to this device";
      flashBtn.onclick = (e) => { e.stopPropagation(); _openFlashDeviceModal(d); };
      actionsEl.appendChild(flashBtn);
    }
    if (d.ip) {
      const portalBtn = el("button", "btn btn-secondary btn-sm", "🌐");
      portalBtn.dataset.tip = `Open device web interface at http://${d.ip}/`;
      portalBtn.onclick = (e) => { e.stopPropagation(); window.open(`http://${d.ip}/`, "_blank"); };
      actionsEl.appendChild(portalBtn);
    }
    const delBtn = el("button", "btn btn-danger btn-sm", "✕");
    delBtn.dataset.tip = "Remove this device from the hub";
    delBtn.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`Remove "${d.name || d.id}"?`)) return;
      await api.devices.delete(d.id).catch(() => {});
      if (onRefresh) onRefresh();
    };
    actionsEl.appendChild(delBtn);

    pill.appendChild(glyphEl);
    pill.appendChild(infoEl);
    pill.appendChild(badge);
    pill.appendChild(actionsEl);
    listEl.appendChild(pill);
  }
}

// ── Shared device card renderer — used by Home dashboard (and legacy Fleet if needed)
function _renderDeviceCards(listEl, devices, onRefresh) {
  if (!devices.length) {
    listEl.innerHTML = '<div class="empty-state">No devices found. Use Scan LAN or + Add Device to discover nodes.</div>';
    return;
  }
  listEl.innerHTML = "";
  for (const d of devices) {
    const online_ = isOnline(d.last_seen);
    const card    = el("div", "device-card");
    const dotClass = online_ ? "device-dot online" : (d.paired ? "device-dot paired" : "device-dot");
    const dotTip   = online_ ? "Online — seen within 2 minutes"
                   : d.paired ? `Offline — last seen ${timeAgo(d.last_seen)}`
                   : "Unregistered — not yet paired";
    card.innerHTML = `
      <span class="${dotClass}" data-tip="${dotTip}"></span>
      <div class="device-info">
        <div class="device-name">${d.name || d.id}</div>
        <div class="device-meta">${d.ip || "no IP"} · ${d.board || "unknown board"} · fw ${d.fw_version || "?"} · ${timeAgo(d.last_seen)}</div>
      </div>
      <span class="device-badge ${d.paired ? "" : "unpaired"}" data-tip="${d.paired ? "Paired — trusted for OTA and commands" : "Not paired — click Pair to enable OTA and commands"}">${d.paired ? "Paired" : "Unpaired"}</span>
    `;
    const actions = el("div", "device-actions");
    if (!d.paired) {
      const pairBtn = el("button", "btn btn-secondary btn-sm", "Pair");
      pairBtn.dataset.tip = "Pair this device with the hub to enable OTA and trusted commands";
      pairBtn.onclick = () => pairDevice(d.id);
      actions.appendChild(pairBtn);
    } else {
      const flashBtn = el("button", "btn btn-secondary btn-sm", "⬆ Flash");
      flashBtn.dataset.tip = "Push firmware to this device — board-compatible entries, newest first";
      flashBtn.onclick = (e) => { e.stopPropagation(); _openFlashDeviceModal(d); };
      actions.appendChild(flashBtn);
    }
    if (d.ip) {
      const portalBtn = el("button", "btn btn-secondary btn-sm", "🌐");
      portalBtn.dataset.tip = `Open device web interface at http://${d.ip}/`;
      portalBtn.onclick = (e) => { e.stopPropagation(); window.open(`http://${d.ip}/`, "_blank"); };
      actions.appendChild(portalBtn);
    }
    const delBtn = el("button", "btn btn-danger btn-sm", "✕");
    delBtn.dataset.tip = "Remove this device from the hub";
    delBtn.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`Remove "${d.name || d.id}"?`)) return;
      await api.devices.delete(d.id).catch(() => {});
      if (onRefresh) onRefresh();
    };
    actions.appendChild(delBtn);
    card.appendChild(actions);
    listEl.appendChild(card);
  }
}

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
  if (listEl) _renderDeviceCards(listEl, devices, loadFleet);
}

async function _openFlashDeviceModal(device) {
  let catalog;
  try { catalog = await api.ota.catalog(); } catch (_) { catalog = []; }
  const compatible = catalog
    .filter(fw => !fw.board || !device.board || fw.board === device.board)
    .sort((a, b) => (b.uploaded || "").localeCompare(a.uploaded || ""));
  if (!compatible.length) {
    openModal("No Compatible Firmware",
      `<div class="empty-state">No firmware in catalog matches board <strong>${device.board || "unknown"}</strong>. Upload a binary first.</div>`,
      [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    return;
  }
  const opts = compatible.map(fw => {
    const fwId  = fw._folder || `${fw.board}-${fw.version}`;
    const label = fw.label || `${fw.board} — v${fw.version}`;
    const tags  = [fw.channel, fw.known_good ? "✓ known good" : ""].filter(Boolean).join(", ");
    return `<option value="${fwId}">${label} (${tags})</option>`;
  }).join("");
  openModal(`Flash — ${device.name || device.id}`, `
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:12px">
      Device: <strong>${device.name || device.id}</strong> · Board: <strong>${device.board || "unknown"}</strong>
    </p>
    <div class="form-field">
      <label data-tip="Board-compatible firmware only, newest first. Known-good builds are labelled.">Firmware</label>
      <select id="flashFwSel">${opts}</select>
    </div>
    <div class="form-field">
      <label data-tip="Logged in the OTA audit trail — your name or a label like 'local' or 'ci'.">Operator</label>
      <input type="text" id="flashOperator" value="local" placeholder="local">
    </div>
  `, [
    { label: "⬆ Flash Now", cls: "btn btn-primary", action: async () => {
      const firmware_id = document.getElementById("flashFwSel").value;
      const operator    = document.getElementById("flashOperator").value.trim() || "local";
      try {
        const result = await api.ota.push({ device_id: device.id, firmware_id, operator });
        closeModal();
        openModal(result.status === "ok" ? "Flash Successful ✓" : "Flash Failed", `
          <p><strong>Status:</strong>
            <span style="color:${result.status === "ok" ? "var(--color-success)" : "var(--color-danger)"}">${result.status}</span>
          </p>
          ${result.response ? `<pre style="font-size:11px;margin-top:8px;overflow:auto;max-height:120px">${result.response}</pre>` : ""}
        `, [{ label: "Close", cls: "btn btn-primary", action: closeModal }]);
      } catch (err) { alert("Flash failed: " + err.message); }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
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
         border-radius:8px;cursor:pointer;position:relative" data-tip="Click to copy">
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

// btnAddDevice wired below via _makeAddDeviceHandler

document.getElementById("btnScan")?.addEventListener("click", _makeScanHandler(loadHome));

// ── Home device action buttons (mirrors fleet — calls loadHome on refresh) ──

function _makeScanHandler(onDone) {
  return async () => {
    openModal("Scanning LAN…", `
      <div style="text-align:center;padding:24px 0">
        <div style="font-size:32px;margin-bottom:12px">📡</div>
        <p style="color:var(--color-text-muted)">Probing 254 addresses on local subnet…</p>
      </div>
    `, []);
    try {
      const result = await api.devices.scan();
      const count  = result.found ?? 0;
      closeModal();
      openModal(`Scan Complete — ${count} node${count !== 1 ? "s" : ""} found`, `
        <p style="margin-bottom:14px;color:var(--color-text-muted);font-size:13px">
          Scanned <code>${result.subnet}.x</code>${count ? " — registered to fleet automatically." : " — no ESPAI nodes responded."}
        </p>
        ${(result.devices || []).map(d => `
          <div class="device-card" style="margin-bottom:6px">
            <span class="device-dot online"></span>
            <div class="device-info">
              <div class="device-name">${d.name || d.id || "Unknown"}</div>
              <div class="device-meta">${d.ip} · ${d.board || "?"} · fw ${d.fw_version || "?"}</div>
            </div>
          </div>`).join("")}
      `, [{ label: "Done", cls: "btn btn-primary", action: () => { closeModal(); onDone(); } }]);
    } catch (err) {
      closeModal();
      openModal("Scan Failed", `<p class="empty-state">${err.message}</p>`,
        [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    }
  };
}

function _makeAddDeviceHandler(onDone) {
  return () => {
    openModal("Add Device Manually", `
      <div class="form-field">
        <label data-tip="The device must be reachable on the local network and running ESPAI firmware">IP Address</label>
        <input type="text" id="manualIP" placeholder="192.168.1.100" style="font-family:monospace">
      </div>
    `, [
      { label: "Add", cls: "btn btn-primary", action: async () => {
        const ip = document.getElementById("manualIP").value.trim();
        if (!ip) return;
        try {
          await api.devices.addManual({ ip });
          closeModal();
          onDone();
        } catch (err) { alert("Error: " + err.message); }
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
    setTimeout(() => document.getElementById("manualIP")?.focus(), 100);
  };
}

document.getElementById("btnHomeScanLAN").onclick    = _makeScanHandler(loadHome);
document.getElementById("btnHomeAddDevice").onclick  = _makeAddDeviceHandler(loadHome);

// ── LAN browser (non-ESPAI devices) ────────────────────────────────────────

function _makeBrowseHandler(onDone) {
  return async () => {
    openModal("Browsing LAN…", `
      <div style="text-align:center;padding:24px 0">
        <div style="font-size:32px;margin-bottom:12px">🔍</div>
        <p style="color:var(--color-text-muted)">Probing all 254 addresses on port 80…</p>
      </div>
    `, []);
    try {
      const result = await api.devices.browse();
      const found  = result.found || [];
      if (!found.length) {
        closeModal();
        openModal("Browse Complete", `<div class="empty-state">No HTTP devices found on <code>${result.subnet}.x</code>.</div>`,
          [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
        return;
      }
      const espai  = found.filter(d => d.is_espai);
      const others = found.filter(d => !d.is_espai);
      const renderRow = d => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--color-card-border)">
          <span style="font-size:18px">${d.is_espai ? "📡" : "🌐"}</span>
          <div style="flex:1;min-width:0">
            <div style="font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${d.title || d.ip}</div>
            <div style="font-size:11px;color:var(--color-text-muted)">${d.ip}${d.server ? " · " + d.server : ""}</div>
          </div>
          <a href="http://${d.ip}/" target="_blank"
             style="font-size:11px;color:var(--color-accent);white-space:nowrap;text-decoration:none"
             data-tip="Open ${d.ip} in a new tab">Open ↗</a>
        </div>`;
      closeModal();
      openModal(`Found ${found.length} device${found.length !== 1 ? "s" : ""} on ${result.subnet}.x`, `
        ${espai.length ? `<p class="section-heading" style="font-size:11px;margin-bottom:4px">ESPAI NODES (${espai.length})</p>${espai.map(renderRow).join("")}` : ""}
        ${others.length ? `<p class="section-heading" style="font-size:11px;margin-top:14px;margin-bottom:4px">OTHER HTTP DEVICES (${others.length})</p>${others.map(renderRow).join("")}` : ""}
      `, [{ label: "Done", cls: "btn btn-primary", action: closeModal }]);
    } catch (err) {
      closeModal();
      openModal("Browse Failed", `<p class="empty-state">${err.message}</p>`,
        [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    }
  };
}

// btnHomeBrowseLAN removed from HTML — no-op placeholder kept to avoid future confusion

document.getElementById("btnBrowseLAN")?.addEventListener("click", _makeBrowseHandler(loadHome));
document.getElementById("btnAddDevice")?.addEventListener("click",  _makeAddDeviceHandler(loadHome));

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

// opts: { projectId, projectName, boardHint, linkedIds }  — all optional
function _openUploadFirmwareModal(opts = {}) {
  const { projectId, projectName, boardHint = "esp32dev", linkedIds = [] } = opts;
  const contextNote = projectId
    ? `<p style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px;line-height:1.6">
         Uploading for <strong>${projectName}</strong> — this firmware will appear in the
         project's <em>Firmware</em> section for one-click flashing to linked devices.
       </p>`
    : `<p style="font-size:13px;color:var(--color-text-muted);margin-bottom:14px;line-height:1.6">
         Upload a compiled <code>.bin</code> from PlatformIO, Arduino IDE, or ESP-IDF.
         In PlatformIO the file is typically at <code>.pio/build/&lt;env&gt;/firmware.bin</code>.
       </p>`;
  openModal("Upload Firmware Binary", `
    ${contextNote}
    <div class="form-field">
      <label data-tip="The compiled firmware binary — .bin format only. Found in .pio/build/&lt;env&gt;/firmware.bin after a PlatformIO build.">Firmware .bin file</label>
      <input type="file" id="fwFile" accept=".bin">
    </div>
    <div class="form-field">
      <label data-tip="Human-readable name shown in the catalog and project firmware list — e.g. 'Jingle Bells v1.2'. Defaults to board name if left blank.">Label (display name)</label>
      <input type="text" id="fwLabel" placeholder="${projectName ? projectName + ' v1.0.0' : 'My Firmware v1.0.0'}" value="${projectName || ''}">
    </div>
    <div class="form-field">
      <label data-tip="Must match your PlatformIO environment name or IDF target exactly (e.g. esp32dev, seeed_xiao_esp32s3). A board mismatch is flagged as a warning when pushing.">Board</label>
      <input type="text" id="fwBoard" placeholder="${boardHint}" value="${boardHint}">
    </div>
    <div class="form-field">
      <label data-tip="Semantic version — increment with every build (e.g. 1.0.0, 1.1.0, 2.0.0).">Version</label>
      <input type="text" id="fwVersion" placeholder="1.0.0" value="1.0.0">
    </div>
    <div class="form-field">
      <label data-tip="Release stage: dev for active development builds, beta for limited rollout testing, stable for production devices.">Channel</label>
      <select id="fwChannel">
        <option value="dev">dev — active development, may be unstable</option>
        <option value="beta">beta — ready for limited testing</option>
        <option value="stable">stable — production-ready release</option>
      </select>
    </div>
  `, [
    { label: "Upload", cls: "btn btn-primary", action: async () => {
      const file    = document.getElementById("fwFile").files[0];
      const label   = document.getElementById("fwLabel").value.trim();
      const board   = document.getElementById("fwBoard").value.trim();
      const version = document.getElementById("fwVersion").value.trim();
      const channel = document.getElementById("fwChannel").value;
      if (!file)           { alert("Select a .bin file."); return; }
      if (!board || !version) { alert("Board and version are required."); return; }
      try {
        await api.ota.upload(file, board, version, channel, label, projectId || "");
        closeModal();
        if (projectId && _currentProject) renderProjectFirmware(_currentProject, linkedIds);
        else loadOTA();
      } catch (err) {
        alert("Upload failed: " + err.message);
      }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
}

document.getElementById("btnUploadFirmware").onclick = () => _openUploadFirmwareModal();

document.getElementById("btnProjUploadFirmware").onclick = async () => {
  if (!_currentProject) return;
  const linkedIds = Array.isArray(_currentProject.devices) ? _currentProject.devices : [];
  let boardHint = "esp32dev";
  if (linkedIds.length) {
    const devs = await api.devices.list().catch(() => []);
    const first = devs.find(d => linkedIds.includes(d.id));
    if (first?.board) boardHint = first.board;
  }
  _openUploadFirmwareModal({
    projectId:   _currentProject.id,
    projectName: _currentProject.name,
    boardHint,
    linkedIds,
  });
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

// ── In-hub code editor ─────────────────────────────────────────────────────

function _cmMode(filePath) {
  const ext = (filePath.split(".").pop() || "").toLowerCase();
  const map = {
    js: "javascript", json: "application/json",
    cpp: "text/x-c++src", c: "text/x-csrc", h: "text/x-c++src", ino: "text/x-c++src",
    py: "text/x-python",
    yaml: "text/x-yaml", yml: "text/x-yaml",
    md: "text/x-markdown",
    html: "text/html", htm: "text/html",
    css: "text/css",
    ini: "text/x-ini", cfg: "text/x-ini",
  };
  return map[ext] || "text/plain";
}

let _activeEditor = null;  // current CodeMirror instance

async function _openFileEditor(projectId, filePath, initialContent = null) {
  let content = initialContent ?? "";
  if (initialContent === null) {
    try {
      const res = await api.projects.readFile(projectId, filePath);
      content = res.content;
    } catch (err) {
      alert("Could not open file: " + err.message);
      return;
    }
  }

  openModal(`✎ ${filePath}`, `
    <div id="codeEditorHost" style="height:460px;border:1px solid var(--color-card-border);border-radius:6px;overflow:hidden;font-size:13px"></div>
    <div id="editorStatus" style="font-size:11px;color:var(--color-text-muted);margin-top:6px;min-height:16px"></div>
  `, [
    { label: "Save", cls: "btn btn-primary", action: async () => {
      if (!_activeEditor) return;
      try {
        await api.projects.writeFile(projectId, filePath, _activeEditor.getValue());
        document.getElementById("editorStatus").textContent = "Saved ✓";
        refreshProjectFiles(projectId);
        setTimeout(closeModal, 600);
      } catch (err) { alert("Save failed: " + err.message); }
    }},
    { label: "Delete", cls: "btn btn-danger", action: async () => {
      if (!confirm(`Delete ${filePath}? This cannot be undone.`)) return;
      try {
        await api.projects.deleteFile(projectId, filePath);
        closeModal();
        refreshProjectFiles(projectId);
      } catch (err) { alert("Delete failed: " + err.message); }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: () => { _activeEditor = null; closeModal(); } },
  ], { wide: true });

  const host = document.getElementById("codeEditorHost");
  if (!host) return;
  if (typeof CodeMirror === "undefined") {
    host.innerHTML = `<textarea style="width:100%;height:100%;background:#111;color:#eee;font-family:monospace;font-size:13px;padding:10px;border:none;resize:none">${content.replace(/</g,"&lt;")}</textarea>`;
    _activeEditor = { getValue: () => host.querySelector("textarea").value };
    return;
  }
  _activeEditor = CodeMirror(host, {
    value: content,
    mode: _cmMode(filePath),
    theme: "dracula",
    lineNumbers: true,
    lineWrapping: true,
    indentUnit: 2,
    tabSize: 2,
    matchBrackets: true,
    autoCloseBrackets: true,
    extraKeys: { Tab: cm => cm.execCommand("insertSoftTab") },
  });
  _activeEditor.setSize("100%", "100%");
  setTimeout(() => _activeEditor.refresh(), 50);
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
        const isEditable = !isBin && f.size_bytes <= 512 * 1024;
        row.innerHTML = `
          <span class="file-path" style="${isEditable ? "cursor:pointer" : ""}">${f.path}${isBin ? ' <span class="tag" style="font-size:10px;padding:1px 5px">BIN</span>' : ""}</span>
          <span class="file-size">${formatBytes(f.size_bytes)}</span>
        `;
        if (isEditable) {
          row.style.cursor = "pointer";
          row.dataset.tip = `Click to edit ${f.path} in the hub editor`;
          row.onclick = () => _openFileEditor(projectId, f.path);
        }
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
  const slugEl = document.getElementById("projDetailSlug");
  if (slugEl) slugEl.textContent = p.slug ? `hostname: ${p.slug}.local` : "";

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
  renderProjectFirmware(p, linkedIds);
  _loadProjectApprovalMode(p.id);
}

const _NODE_ROLES = ["coordinator","sensor","actuator","gateway","observer","hub-agent","relay","node"];
const _TOPOLOGIES = ["standalone","star","mesh","hub-spoke","pipeline","custom"];
const _APP_TYPES  = ["firmware","hub","hybrid"];

const _TOPOLOGY_ICONS = {
  standalone:"◎", star:"✦", mesh:"⬡", "hub-spoke":"⊙", pipeline:"→", custom:"◈"
};
const _APP_TYPE_LABELS = { firmware:"Firmware", hub:"Hub App", hybrid:"Hybrid" };

async function renderProjectDevices(project, linkedIds) {
  // Delegate to the new node-aware renderer
  await renderProjectNodes(project);
}

async function renderProjectNodes(project) {
  const devList = document.getElementById("projDeviceList");
  devList.innerHTML = '<div class="empty-state" style="font-size:12px">Loading nodes…</div>';

  const [allDevs, nodes, topoData] = await Promise.all([
    api.devices.list().catch(() => []),
    api.projects.nodes(project.id).catch(() => []),
    api.projects.topology(project.id).catch(() => ({ topology:"standalone", app_type:"firmware" })),
  ]);
  const devMap = new Map(allDevs.map(d => [d.id, d]));
  const linkedIds = nodes.map(n => n.device_id);

  devList.innerHTML = "";

  // ── Topology + app-type header ──────────────────────────────────────────
  const topoBar = el("div", "");
  topoBar.style.cssText = "display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap";

  const topoSel = document.createElement("select");
  topoSel.style.cssText = "background:var(--color-surface);border:1px solid var(--color-card-border);border-radius:5px;padding:3px 8px;font-size:11px;color:var(--color-text);font-family:monospace";
  topoSel.dataset.tip = "Network topology — how nodes in this project communicate with each other";
  _TOPOLOGIES.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = `${_TOPOLOGY_ICONS[t] || "◈"} ${t}`;
    if (t === topoData.topology) opt.selected = true;
    topoSel.appendChild(opt);
  });

  const appSel = document.createElement("select");
  appSel.style.cssText = topoSel.style.cssText;
  appSel.dataset.tip = "Where the primary app logic runs — firmware on ESP32, hub-side, or both";
  _APP_TYPES.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = _APP_TYPE_LABELS[t];
    if (t === topoData.app_type) opt.selected = true;
    appSel.appendChild(opt);
  });

  const saveTopoBtn = el("button", "btn btn-secondary btn-sm", "Save");
  saveTopoBtn.dataset.tip = "Save topology and app type settings";
  saveTopoBtn.onclick = async () => {
    await api.projects.setTopology(project.id, {
      topology: topoSel.value,
      app_type: appSel.value,
    }).catch(e => alert(e.message));
    saveTopoBtn.textContent = "Saved ✓";
    setTimeout(() => { saveTopoBtn.textContent = "Save"; }, 1200);
  };

  topoBar.appendChild(el("span", "", "Topology:"));
  topoBar.appendChild(topoSel);
  topoBar.appendChild(el("span", "", "App:"));
  topoBar.appendChild(appSel);
  topoBar.appendChild(saveTopoBtn);
  devList.appendChild(topoBar);

  // ── Node rows ────────────────────────────────────────────────────────────
  const nodesEl = el("div", "");
  nodesEl.id = "projNodeRows";

  if (nodes.length) {
    for (const node of nodes) {
      const did  = node.device_id;
      const dev  = devMap.get(did);
      const online = dev && isOnline(dev.last_seen);
      const pillColor = online ? "var(--color-success)" : dev?.paired ? "var(--color-text-muted)" : "#546e7a";
      const roleCls = `node-role node-role-${node.role || "node"}`;

      const row = el("div", "node-row");
      row.style.setProperty("--pill-color", pillColor);

      // Status glyph
      const glyph = el("span", "");
      glyph.style.cssText = `width:8px;height:8px;border-radius:50%;background:${pillColor};box-shadow:0 0 5px ${pillColor};flex-shrink:0`;
      glyph.dataset.tip = online ? "Online" : `Last seen: ${dev?.last_seen ? timeAgo(dev.last_seen) : "never"}`;

      // Info
      const info = el("div", "node-row-info");
      const nameEl = el("div", "node-row-name");
      nameEl.textContent = node.label || dev?.name || did;
      const metaEl = el("div", "node-row-meta");
      metaEl.textContent = [dev?.ip || "no IP", dev?.board || "?", dev?.fw_version ? `fw ${dev.fw_version}` : ""].filter(Boolean).join(" · ");
      info.appendChild(nameEl);
      info.appendChild(metaEl);

      const roleBadge = el("span", roleCls, node.role || "node");
      roleBadge.dataset.tip = `Node role: ${node.role || "node"}`;

      const actions = el("div", "node-row-actions");

      // Set role button
      const roleBtn = el("button", "btn btn-secondary btn-sm", "⚙ Role");
      roleBtn.dataset.tip = "Change this node's role in the project";
      roleBtn.onclick = () => _openNodeRoleModal(project, node, dev, () => renderProjectNodes(project));
      actions.appendChild(roleBtn);

      if (dev?.ip) {
        const portalBtn = el("button", "btn btn-secondary btn-sm", "🌐");
        portalBtn.dataset.tip = `Open device portal at http://${dev.ip}/`;
        portalBtn.onclick = () => window.open(`http://${dev.ip}/`, "_blank");
        actions.appendChild(portalBtn);
      }
      const removeBtn = el("button", "btn btn-danger btn-sm", "✕");
      removeBtn.dataset.tip = "Remove this node from the project — the device stays in Fleet";
      removeBtn.onclick = async () => {
        await api.projects.removeNode(project.id, did).catch(() => {});
        project.devices = (project.devices || []).filter(id => id !== did);
        renderProjectNodes(project);
      };
      actions.appendChild(removeBtn);

      row.appendChild(glyph);
      row.appendChild(info);
      row.appendChild(roleBadge);
      row.appendChild(actions);
      nodesEl.appendChild(row);
    }
  } else {
    nodesEl.appendChild(el("div", "empty-state", "No nodes linked yet. Click Find Node or + Link."));
  }
  devList.appendChild(nodesEl);

  const btnRow = el("div", "");
  btnRow.style.cssText = "display:flex;gap:6px;margin-top:10px;flex-wrap:wrap";

  // Find Node — scans LAN + allows role assignment
  const findBtn = el("button", "btn btn-primary btn-sm", "📡 Find Node");
  findBtn.dataset.tip = "Scan the LAN for ESPAI nodes and add them to this project with a role";
  findBtn.onclick = async () => {
    findBtn.textContent = "Scanning…";
    findBtn.disabled = true;
    try { await api.devices.scan(); } catch (_) {}
    let freshDevs;
    try { freshDevs = await api.devices.list(); } catch (_) { freshDevs = []; }
    findBtn.textContent = "📡 Find Node";
    findBtn.disabled = false;

    const candidates = freshDevs.filter(d => !linkedIds.includes(d.id));
    if (!candidates.length) {
      openModal("No New Nodes", '<div class="empty-state">No additional ESPAI nodes found. Make sure the device is powered and on the same network.</div>',
        [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
      return;
    }
    const roleOpts = _NODE_ROLES.map(r => `<option value="${r}">${r}</option>`).join("");
    const devRows = candidates.map(d => `
      <label style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--color-card-border);cursor:pointer">
        <input type="checkbox" value="${d.id}">
        <div style="flex:1">
          <div style="font-weight:600">${d.name || d.id}</div>
          <div style="font-size:11px;color:var(--color-text-muted)">${d.ip || "no IP"} · ${d.board || "?"} · ${d.paired ? "✓ paired" : "⚠ unpaired"}</div>
        </div>
        <select class="link-role-sel" style="font-size:10px;background:var(--color-surface);border:1px solid var(--color-card-border);border-radius:4px;padding:2px 6px;color:var(--color-text)">${roleOpts}</select>
      </label>`).join("");
    openModal("Find & Link Nodes", `
      <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px">Select nodes to add. Assign a role to each. Unpaired devices will be paired automatically.</p>
      <div>${devRows}</div>
    `, [
      { label: "Add Selected", cls: "btn btn-primary", action: async () => {
        const checkboxes = [...document.querySelectorAll("#modalBody input[type=checkbox]:checked")];
        if (!checkboxes.length) { closeModal(); return; }
        for (const cb of checkboxes) {
          const did = cb.value;
          const roleEl = cb.closest("label")?.querySelector(".link-role-sel");
          const role = roleEl?.value || "node";
          const freshMap = new Map(freshDevs.map(d => [d.id, d]));
          const d = freshMap.get(did);
          if (d && !d.paired) await api.devices.initiatePair(did).catch(() => {});
          await api.projects.upsertNode(project.id, did, { role, node_index: linkedIds.length }).catch(() => {});
        }
        closeModal();
        renderProjectNodes(project);
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
  };
  btnRow.appendChild(findBtn);

  const linkBtn = el("button", "btn btn-secondary btn-sm", "+ Link Existing");
  linkBtn.dataset.tip = "Link a fleet device to this project and assign its role";
  linkBtn.onclick = () => {
    const available = allDevs.filter(d => !linkedIds.includes(d.id));
    if (!available.length) {
      openModal("No Available Devices", '<div class="empty-state">All fleet devices are already linked, or fleet is empty.</div>',
        [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
      return;
    }
    const devOpts = available.map(d =>
      `<option value="${d.id}">${d.name || d.id} · ${d.board || "?"}</option>`
    ).join("");
    const roleOpts = _NODE_ROLES.map(r => `<option value="${r}">${r}</option>`).join("");
    openModal("Link Node to Project", `
      <div class="form-field">
        <label data-tip="Fleet device to add as a node">Device</label>
        <select id="linkDevSel">${devOpts}</select>
      </div>
      <div class="form-field" style="margin-top:10px">
        <label data-tip="Role this node plays in the project">Role</label>
        <select id="linkRoleSel">${roleOpts}</select>
      </div>
      <div class="form-field" style="margin-top:10px">
        <label data-tip="Optional human-readable label for this node instance">Label (optional)</label>
        <input type="text" id="linkLabelInp" placeholder="e.g. North Gateway, Bedroom Sensor" style="width:100%">
      </div>
    `, [
      { label: "Link", cls: "btn btn-primary", action: async () => {
        const did   = document.getElementById("linkDevSel")?.value;
        const role  = document.getElementById("linkRoleSel")?.value || "node";
        const label = document.getElementById("linkLabelInp")?.value?.trim() || null;
        await api.projects.upsertNode(project.id, did, { role, label, node_index: linkedIds.length }).catch(() => {});
        closeModal();
        renderProjectNodes(project);
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
  };
  btnRow.appendChild(linkBtn);
  devList.appendChild(btnRow);
}

function _openNodeRoleModal(project, node, dev, onSave) {
  const roleOpts = _NODE_ROLES.map(r =>
    `<option value="${r}" ${r === node.role ? "selected" : ""}>${r}</option>`
  ).join("");
  const devName = node.label || dev?.name || node.device_id;
  openModal(`Node Role — ${devName}`, `
    <div class="form-field">
      <label data-tip="Role this node plays in the project — affects how the hub routes events and which firmware build flags to apply">Role</label>
      <select id="nodeRoleSel">${roleOpts}</select>
    </div>
    <div class="form-field" style="margin-top:10px">
      <label data-tip="Optional friendly label for this specific node instance">Label</label>
      <input type="text" id="nodeLabelInp" value="${node.label || ""}" placeholder="e.g. North Gateway, Living Room Sensor" style="width:100%">
    </div>
    <p style="font-size:11px;color:var(--color-text-muted);margin-top:10px;line-height:1.5">
      Roles: <strong>coordinator</strong> (mesh hub) · <strong>sensor</strong> (data collection) ·
      <strong>actuator</strong> (output/control) · <strong>gateway</strong> (bridges other networks) ·
      <strong>observer</strong> (passive monitoring) · <strong>hub-agent</strong> (hub-side process) ·
      <strong>relay</strong> (packet forwarding) · <strong>node</strong> (generic)
    </p>
  `, [
    { label: "Save", cls: "btn btn-primary", action: async () => {
      const role  = document.getElementById("nodeRoleSel")?.value || "node";
      const label = document.getElementById("nodeLabelInp")?.value?.trim() || null;
      await api.projects.upsertNode(project.id, node.device_id, { role, label, node_index: node.node_index || 0 }).catch(e => alert(e.message));
      closeModal();
      if (onSave) onSave();
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
}

async function renderProjectFirmware(project, linkedIds) {
  const listEl = document.getElementById("projFirmwareList");
  if (!listEl) return;
  listEl.innerHTML = '<div class="empty-state" style="font-size:12px">Loading…</div>';

  let catalog;
  try { catalog = await api.ota.catalogByProject(project.id); }
  catch (_) { catalog = []; }

  if (!catalog.length) {
    listEl.innerHTML = '<div class="empty-state">No firmware tagged to this project yet. Click ⬆ Upload Firmware to add one.</div>';
    return;
  }

  catalog.sort((a, b) => (b.uploaded || "").localeCompare(a.uploaded || ""));
  listEl.innerHTML = "";
  for (const fw of catalog) {
    const row = el("div", "file-row");
    const displayName = fw.label || `${fw.board} — v${fw.version}`;
    const goodBadge = fw.known_good
      ? `<span class="tag" style="background:rgba(26,175,100,.15);color:#1aaf64;border-color:rgba(26,175,100,.3)">✓ Good</span>`
      : "";
    row.innerHTML = `
      <span class="file-path" data-tip="Board: ${fw.board} · Version: ${fw.version} · ${fw.channel}">${displayName}</span>
      <span class="file-size">${fw.board} · v${fw.version} · ${fw.channel} · ${formatBytes(fw.size_bytes)}</span>
      <span class="file-ts" data-tip="${fw.uploaded || ''}">${timeAgo(fw.uploaded)}</span>
      ${goodBadge}
    `;
    const flashBtn = el("button", "btn btn-primary btn-sm", "⬆ Flash");
    flashBtn.style.marginLeft = "auto";
    flashBtn.dataset.tip = "Push this firmware to a device linked to this project — skips the OTA catalog view";
    flashBtn.onclick = () => openPushModal(fw, linkedIds);
    row.appendChild(flashBtn);
    listEl.appendChild(row);
  }
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

document.getElementById("btnNewFile").onclick = () => {
  if (!_currentProject) return;
  openModal("New File", `
    <div class="form-field">
      <label data-tip="Path relative to the project directory — e.g. web/index.html, src/sensor.cpp, data/config.yaml">File path (relative to project)</label>
      <input type="text" id="newFilePath" placeholder="web/index.html" style="font-family:monospace">
    </div>
    <p style="font-size:12px;color:var(--color-text-muted);margin-top:8px">The file will open in the editor after creation.</p>
  `, [
    { label: "Create", cls: "btn btn-primary", action: async () => {
      const path = document.getElementById("newFilePath").value.trim();
      if (!path) { alert("Enter a file path."); return; }
      try {
        await api.projects.createFile(_currentProject.id, path, "");
        closeModal();
        await refreshProjectFiles(_currentProject.id);
        _openFileEditor(_currentProject.id, path, "");
      } catch (err) { alert("Create failed: " + err.message); }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
  setTimeout(() => document.getElementById("newFilePath")?.focus(), 100);
};

// ── Project approval mode selector ─────────────────────────────────────────

let _projApprovalMode = "dev";

async function _loadProjectApprovalMode(projectId) {
  try {
    const { mode } = await api.projects.approvalMode(projectId);
    _projApprovalMode = mode || "dev";
  } catch (_) {
    _projApprovalMode = "dev";
  }
  _renderApprovalModeSeg(_projApprovalMode);
}

function _renderApprovalModeSeg(mode) {
  document.querySelectorAll(".proj-mode-btn").forEach(btn => {
    const isActive = btn.dataset.mode === mode;
    btn.classList.toggle("active", isActive);
  });
  const bar = document.getElementById("projModeBar");
  if (bar) {
    bar.dataset.mode = mode;
    bar.style.borderColor = mode === "prototype" ? "rgba(26,175,100,.4)"
                          : mode === "stable"    ? "rgba(230,140,60,.4)"
                          : "rgba(255,255,255,.08)";
  }
}

document.getElementById("projModeSeg").addEventListener("click", async (e) => {
  const btn = e.target.closest(".proj-mode-btn");
  if (!btn || !_currentProject) return;
  const mode = btn.dataset.mode;
  try {
    await api.projects.setApprovalMode(_currentProject.id, mode);
    _projApprovalMode = mode;
    _renderApprovalModeSeg(mode);
  } catch (err) { alert("Error: " + err.message); }
});

document.getElementById("btnProjGitLog").onclick = async () => {
  if (!_currentProject) return;
  try {
    const { commits, is_repo } = await api.projects.gitLog(_currentProject.id, 40);
    if (!is_repo) {
      openModal("No Git History", `
        <div class="empty-state">
          This project does not have a git repository.<br>
          <span style="font-size:12px">New projects auto-initialize git — existing projects can be initialized via the terminal.</span>
        </div>
      `, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
      return;
    }
    const rows = commits.length
      ? commits.map(c => `
          <div style="display:flex;gap:10px;align-items:flex-start;padding:7px 0;border-bottom:1px solid var(--color-card-border)">
            <code style="font-size:10px;color:var(--color-accent);white-space:nowrap;margin-top:2px">${c.hash}</code>
            <div style="flex:1;min-width:0">
              <div style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${c.message}</div>
              <div style="font-size:11px;color:var(--color-text-muted)">${c.author} · ${timeAgo(c.timestamp)}</div>
            </div>
          </div>`).join("")
      : '<div class="empty-state">No commits yet.</div>';
    openModal(`Git History — ${_currentProject.name}`, `
      <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px">
        Last ${commits.length} commit${commits.length !== 1 ? "s" : ""}. Every file save and approved agent task is auto-committed.
      </p>
      <div style="max-height:400px;overflow-y:auto">${rows}</div>
    `, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
  } catch (err) { alert("Error: " + err.message); }
};

document.getElementById("btnProjApplyTheme").onclick = async () => {
  if (!_currentProject) return;
  try {
    const result = await api.projects.applyHubTheme(_currentProject.id);
    openModal("Hub Theme Applied", `
      <p style="font-size:13px;line-height:1.6;margin-bottom:10px">
        Generated <code>web/hub-theme.css</code> with <strong>${result.token_count}</strong>
        design tokens from the <strong>${result.theme}</strong> theme.
      </p>
      <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px">
        Add this line to your project's <code>web/index.html</code> to activate it:
      </p>
      <pre style="font-size:11px;background:var(--color-surface);border:1px solid var(--color-card-border);border-radius:6px;padding:10px;overflow:auto">${result.link_tag}</pre>
    `, [
      { label: "Copy Link Tag", cls: "btn btn-primary", action: () => {
        navigator.clipboard?.writeText(result.link_tag).catch(() => {});
        closeModal();
      }},
      { label: "Close", cls: "btn btn-secondary", action: closeModal },
    ]);
  } catch (err) { alert("Apply theme failed: " + err.message); }
};

document.getElementById("btnProjRegenCtx").onclick = async () => {
  if (!_currentProject) return;
  try {
    await api.projects.regenerateContext(_currentProject.id);
    // Refresh file list so ESPAI.md shows up
    refreshProjectFiles(_currentProject.id);
    openModal("Context Regenerated", `
      <p>The <code>ESPAI.md</code> file for <strong>${_currentProject.name}</strong> has been updated.</p>
      <p style="font-size:12px;color:var(--color-text-muted);margin-top:8px">
        Agents will receive this file before every task prompt for this project.
      </p>
    `, [{ label: "Close", cls: "btn btn-primary", action: closeModal }]);
  } catch (err) { alert("Error: " + err.message); }
};

document.getElementById("btnProjTheme").onclick = async () => {
  if (!_currentProject) return;
  const [current, themes] = await Promise.all([
    api.projects.theme(_currentProject.id).catch(() => ({ project_overrides: {} })),
    api.design.themes().catch(() => []),
  ]);
  const active = current.project_overrides || {};
  const hasOverrides = Object.keys(active).length > 0;

  const SWATCH_KEYS = ["color.background","color.surface","color.card","color.accent","color.accent2","color.warning","color.success","color.text"];

  const themeCards = themes.map(t => {
    const tokens = t.tokens || {};
    const swatches = SWATCH_KEYS.filter(k => tokens[k])
      .map(k => `<div style="flex:1;height:32px;background:${tokens[k]}"></div>`).join("");
    const isActive = hasOverrides && JSON.stringify(active) === JSON.stringify(tokens);
    return `
      <div class="theme-card${isActive ? " active" : ""}" style="cursor:pointer" data-theme="${t.name}" data-tip="Apply ${t.display_name || t.name} tokens to this project">
        <div class="theme-palette" style="height:32px">${swatches}</div>
        <div class="theme-card-body" style="padding:8px 10px">
          <div class="theme-card-name">${t.display_name || t.name}</div>
          ${isActive ? '<div style="margin-top:4px"><span class="theme-active-badge">ACTIVE ON PROJECT</span></div>' : ""}
        </div>
      </div>`;
  }).join("");

  openModal(`Project Theme — ${_currentProject.name}`, `
    <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px;line-height:1.6">
      Apply a hub theme as project-specific overrides — active only while this project is open.
      Or enter custom token overrides in the JSON editor below.
    </p>
    <div class="home-band-hd" style="margin-bottom:10px">
      <span class="home-band-label">Hub Themes</span>
    </div>
    <div class="theme-mgr-grid" id="projThemeGrid" style="margin-bottom:16px">${themeCards}</div>
    <details style="margin-bottom:8px">
      <summary style="font-size:11px;color:var(--color-accent);cursor:pointer;font-family:monospace;letter-spacing:.06em;text-transform:uppercase">Custom Token Overrides (JSON)</summary>
      <div class="form-field" style="margin-top:8px">
        <textarea id="projThemeJson" rows="5" style="font-family:monospace;font-size:11px">${JSON.stringify(active, null, 2)}</textarea>
      </div>
    </details>
    <p id="projThemeStatus" style="font-size:12px;min-height:14px;color:var(--color-success)"></p>
  `, [
    { label: "Save & Apply", cls: "btn btn-primary", action: async () => {
      const raw = document.getElementById("projThemeJson")?.value || "{}";
      let overrides;
      try { overrides = JSON.parse(raw); } catch (_) {
        document.getElementById("projThemeStatus").textContent = "Invalid JSON"; return;
      }
      await api.projects.setTheme(_currentProject.id, { theme_overrides: overrides }).catch(() => {});
      _applyProjectTheme(overrides);
      closeModal();
    }},
    { label: "Clear", cls: "btn btn-secondary", action: async () => {
      await api.projects.setTheme(_currentProject.id, { theme_overrides: {} }).catch(() => {});
      _clearProjectTheme();
      closeModal();
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ], { wide: true });

  // Wire theme card clicks → populate JSON editor
  setTimeout(() => {
    document.querySelectorAll("#projThemeGrid .theme-card").forEach(card => {
      card.onclick = async () => {
        const name = card.dataset.theme;
        const t    = themes.find(x => x.name === name);
        if (!t) return;
        const ta = document.getElementById("projThemeJson");
        if (ta) ta.value = JSON.stringify(t.tokens || {}, null, 2);
        document.querySelectorAll("#projThemeGrid .theme-card").forEach(c => c.classList.remove("active"));
        card.classList.add("active");
        const s = document.getElementById("projThemeStatus");
        if (s) s.textContent = `${t.display_name || name} tokens loaded — click Save & Apply to activate`;
      };
    });
  }, 50);
};

async function _projFirmwareRoot(projId) {
  const info = await api.projects.files(projId).catch(() => null);
  return info?.root ? info.root.replace(/\//g, "\\") + "\\firmware" : null;
}

document.getElementById("btnProjRename").onclick = async () => {
  if (!_currentProject) return;
  const current = _currentProject.name;
  openModal("Rename Project", `
    <p style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px;line-height:1.6">
      Project names are automatically converted to hostname format
      (lowercase letters, digits, hyphens only). The new name becomes the mDNS
      hostname and web app slug immediately.
    </p>
    <div class="form-field">
      <label>New name</label>
      <input id="renameInput" type="text" value="${current}" style="width:100%">
    </div>
    <p id="renamePreview" style="font-size:11px;color:var(--color-text-muted);margin-top:6px"></p>
  `, [
    { label: "Rename", cls: "btn btn-primary", action: async () => {
      const val = document.getElementById("renameInput").value.trim();
      if (!val) return;
      try {
        const result = await api.projects.rename(_currentProject.id, { name: val });
        _currentProject.name = result.name;
        _currentProject.slug = result.slug;
        document.getElementById("projDetailName").textContent = result.name;
        const slugEl = document.getElementById("projDetailSlug");
        if (slugEl) slugEl.textContent = `hostname: ${result.slug}.local`;
        closeModal();
      } catch (err) { alert("Rename failed: " + err.message); }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
  // Live preview of hostname conversion
  const input = document.getElementById("renameInput");
  const preview = document.getElementById("renamePreview");
  const toSlug = s => s.toLowerCase().replace(/[\s_]+/g, "-").replace(/[^a-z0-9-]/g, "").replace(/-{2,}/g, "-").replace(/^-+|-+$/g, "");
  input.oninput = () => { preview.textContent = input.value ? `→ hostname: ${toSlug(input.value)}.local` : ""; };
  input.oninput();
};

document.getElementById("btnProjOpenApp").onclick = async () => {
  if (!_currentProject) return;
  try {
    const { url, host } = await api.projects.appUrl(_currentProject.id);
    if (url) {
      window.open(url, "_blank");
    } else {
      alert("No web interface found for this project.\n\nAdd a web/index.html to the project folder to host it on the hub, or link a device so the hub can find its IP.");
    }
  } catch (err) { alert("Could not resolve app URL: " + err.message); }
};

document.getElementById("btnProjBuild").onclick = async () => {
  if (!_currentProject) return;
  const root = await _projFirmwareRoot(_currentProject.id);
  showView("terminal");
  await new Promise(r => setTimeout(r, 150));
  _termNewSession({
    title: `Build — ${_currentProject.name}`,
    cwd: root || undefined,
    init_cmds: root
      ? ["pio run"]
      : ['Write-Host "Could not find firmware/ directory" -ForegroundColor Red'],
  });
};

document.getElementById("btnProjImport").onclick = async () => {
  if (!_currentProject) return;
  const btn = document.getElementById("btnProjImport");
  const orig = btn.textContent;
  btn.textContent = "Importing…";
  btn.disabled = true;
  try {
    const meta = await api.projects.importBuild(_currentProject.id, "dev");
    const linkedIds = Array.isArray(_currentProject.devices) ? _currentProject.devices : [];
    // Refresh the project Firmware section — stays in project, no navigation needed
    await renderProjectFirmware(_currentProject, linkedIds);
    // Brief inline confirmation on the button itself, no modal
    btn.textContent = "✓ Imported";
    btn.style.color = "var(--color-success)";
    setTimeout(() => { btn.textContent = orig; btn.style.color = ""; }, 2500);
  } catch (err) {
    alert("Import failed: " + err.message);
  } finally {
    btn.textContent = orig;
    btn.disabled = false;
  }
};

document.getElementById("btnProjFlashUSB").onclick = async () => {
  if (!_currentProject) return;
  const root = await _projFirmwareRoot(_currentProject.id);
  showView("terminal");
  await new Promise(r => setTimeout(r, 150));
  _termNewSession({
    title: `Flash USB — ${_currentProject.name}`,
    cwd: root || undefined,
    init_cmds: root
      ? ['Write-Host "Flashing via USB — make sure the device is connected" -ForegroundColor Yellow', "pio run -t upload"]
      : ['Write-Host "Could not find firmware/ directory" -ForegroundColor Red'],
  });
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
  openModal("Import Project ZIP", `
    <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:14px;line-height:1.6">
      Upload a <strong>.zip</strong> of any PlatformIO or Arduino IDE project.
      Build artifacts (<code>.pio/</code>, <code>node_modules/</code>) are stripped automatically.
      After import a draft <strong>port-to-hub</strong> Agent Bench task is created — run it
      to have Claude analyse the firmware and build out the ESPAI integration.
    </p>
    <div class="form-field">
      <label data-tip="ZIP file containing your PlatformIO or Arduino project — up to 100 MB">Project ZIP</label>
      <input type="file" id="importZip" accept=".zip" style="font-size:13px">
    </div>
    <div class="form-field">
      <label data-tip="Name shown in the project list — defaults to the ZIP filename if left blank">Project Name (optional)</label>
      <input type="text" id="importName" placeholder="e.g. Motion Sensor Node">
    </div>
    <div class="form-field">
      <label data-tip="Passed to the agent as context about what this project does">Description (optional)</label>
      <textarea id="importDesc" rows="2" placeholder="e.g. PIR motion sensor on GPIO 14 — reports to hub and blinks LED on trigger"></textarea>
    </div>
    <div id="importProgress" style="display:none;margin-top:10px">
      <div style="height:4px;background:var(--color-card-border);border-radius:2px;overflow:hidden">
        <div id="importBar" style="height:100%;width:0%;background:var(--color-accent);transition:width .2s"></div>
      </div>
    </div>
    <p id="importStatus" style="font-size:12px;color:var(--color-accent);margin-top:8px;min-height:14px"></p>
  `, [
    { label: "Import & Create Task", cls: "btn btn-primary", action: async () => {
      const zipInput  = document.getElementById("importZip");
      const name      = document.getElementById("importName").value.trim();
      const desc      = document.getElementById("importDesc").value.trim();
      const statusEl  = document.getElementById("importStatus");
      const progressEl = document.getElementById("importProgress");
      const barEl     = document.getElementById("importBar");

      if (!zipInput.files.length) {
        if (statusEl) statusEl.textContent = "Choose a .zip file first.";
        return;
      }
      const zipFile = zipInput.files[0];

      const fd = new FormData();
      fd.append("file", zipFile);
      if (name) fd.append("name", name);
      if (desc)  fd.append("description", desc);

      if (statusEl) statusEl.textContent = "Uploading…";
      if (progressEl) progressEl.style.display = "block";

      try {
        // XHR for upload progress
        const result = await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", "/api/projects/import-zip");
          xhr.upload.onprogress = e => {
            if (e.lengthComputable && barEl)
              barEl.style.width = Math.round(e.loaded / e.total * 80) + "%";
          };
          xhr.onload = () => {
            if (barEl) barEl.style.width = "100%";
            if (xhr.status >= 200 && xhr.status < 300) {
              try { resolve(JSON.parse(xhr.responseText)); }
              catch { reject(new Error("Invalid response")); }
            } else {
              try { reject(new Error(JSON.parse(xhr.responseText).detail || "Upload failed")); }
              catch { reject(new Error(`HTTP ${xhr.status}`)); }
            }
          };
          xhr.onerror = () => reject(new Error("Network error"));
          xhr.send(fd);
        });

        closeModal();
        const typeLabel = result.has_platformio ? "PlatformIO" : result.has_arduino ? "Arduino IDE" : "Unknown";
        const taskNote  = result.task_id
          ? `<p style="font-size:13px;color:var(--color-text-muted);margin-top:10px;line-height:1.6">
               A draft <strong>port-to-hub</strong> Agent Bench task has been created.
               Open the project → Agent Tasks section to review and run it.
             </p>`
          : `<div style="margin-top:12px;font-size:12px;line-height:1.7">
               <p style="color:var(--color-text-muted);margin-bottom:6px">
                 Agent Bench is disabled. Manual porting steps:
               </p>
               <ol style="margin:0;padding-left:18px;color:var(--color-text-muted)">
                 <li>Open the project → browse <code>source/</code> in the file editor</li>
                 <li>Create hub <strong>Workers</strong> for any processing that ran on the ESP32</li>
                 <li>Create <strong>Cards</strong> for sensor dashboards the firmware served locally</li>
                 <li>Edit <code>firmware/src/main.cpp</code> — add hub checkin calls, remove local web server</li>
                 <li>Build with <code>pio run</code> → import the <code>.bin</code> via OTA → flash to device</li>
               </ol>
             </div>`;

        openModal("Import Complete ✓", `
          <p style="margin-bottom:6px">
            <strong>${result.name}</strong> imported — ${result.file_count} files extracted.
          </p>
          <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:4px">
            Project type: <strong>${typeLabel}</strong> &nbsp;·&nbsp;
            Source preserved in <code>source/</code>
          </p>
          ${taskNote}
        `, [{ label: "Open Project", cls: "btn btn-primary", action: async () => {
          closeModal();
          const p = await api.projects.get(result.id).catch(() => null);
          if (p) openProject(p); else loadProjects();
        }}]);
      } catch (err) {
        if (progressEl) progressEl.style.display = "none";
        if (statusEl) statusEl.textContent = "Error: " + err.message;
      }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
};

// ── Registry views (recipes, workers, cards) ───────────────────────────────

function _packBadge(item) {
  const pack = item._pack || "official";
  const tip  = pack === "custom"
    ? "Custom (local only) — stored in custom/ subfolder, gitignored"
    : "Official — tracked in git and published to GitHub";
  return `<span class="pack-badge ${pack}" data-tip="${tip}">${pack === "custom" ? "⚙ Custom" : "★ Official"}</span>`;
}

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
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px">
        <div class="reg-card-title">${title}</div>
        ${_packBadge(item)}
      </div>
      ${sub ? `<div class="reg-card-sub">${sub}</div>` : ""}
      <div class="tag-row">${tags}</div>
    `;
    el_.appendChild(card);
  }
}

async function loadRecipes() {
  const items = await api.recipes.list().catch(() => []);
  const el_ = document.getElementById("recipeList");
  if (!items.length) { el_.innerHTML = '<div class="empty-state">Nothing found.</div>'; return; }
  el_.innerHTML = "";
  for (const item of items) {
    const rname = item._folder || item.name;
    const title = item.name || rname || "—";
    const sub   = item.category || "";
    const tags  = [
      ...(item.compatibility?.compatible_boards || []).map(b => `<span class="tag">${b}</span>`),
      ...(item.requires_workers || []).map(w => `<span class="tag accent">${w}</span>`),
    ].slice(0, 5).join("");

    const card = el("div", "reg-card");
    card.innerHTML = `
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px">
        <div class="reg-card-title">${title}</div>
        ${_packBadge(item)}
      </div>
      ${sub ? `<div class="reg-card-sub">${sub}</div>` : ""}
      ${item.summary ? `<div style="font-size:11px;color:var(--color-text-muted);margin-top:4px;line-height:1.5;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">${item.summary}</div>` : ""}
      <div class="tag-row">${tags}</div>`;

    const btnRow = el("div", "");
    btnRow.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;margin-top:10px";

    const editBtn = el("button", "btn btn-secondary btn-sm", "📁 Edit");
    editBtn.dataset.tip = "Browse and edit this recipe's YAML files in the hub editor";
    editBtn.onclick = () => _openRegistryEditor("recipe", rname, title);
    btnRow.appendChild(editBtn);

    const delBtn = el("button", "btn btn-danger btn-sm", "✕");
    delBtn.dataset.tip = "Permanently delete this recipe and all its files";
    delBtn.onclick = async () => {
      if (!confirm(`Delete recipe "${title}"? This cannot be undone.`)) return;
      try { await api.recipes.delete(rname); loadRecipes(); }
      catch (err) { alert("Delete failed: " + err.message); }
    };
    btnRow.appendChild(delBtn);

    card.appendChild(btnRow);
    el_.appendChild(card);
  }
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
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px">
        <div class="reg-card-title">${title}</div>
        ${_packBadge(item)}
      </div>
      ${sub ? `<div class="reg-card-sub">${sub}</div>` : ""}
      <div class="tag-row">
        ${tags}
        <span class="tag" data-tip="Filesystem access level: ${fs}" style="opacity:.7">fs:${fs}</span>
        <span class="tag" data-tip="Network access level: ${net}" style="opacity:.7">net:${net}</span>
        ${item.quarantine ? '<span class="tag" data-tip="Imported or generated worker — runs sandboxed until reviewed" style="color:var(--color-warning)">quarantined</span>' : ""}
      </div>
    `;
    const wname = item.name || item._folder;
    const btnRow = el("div", "");
    btnRow.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;margin-top:10px";

    const testBtn = el("button", "btn btn-secondary btn-sm", "▶ Test");
    testBtn.dataset.tip = "Run this worker with test inputs and see the output immediately";
    testBtn.onclick = () => openWorkerTestModal(item);
    btnRow.appendChild(testBtn);

    const editBtn = el("button", "btn btn-secondary btn-sm", "📁 Edit");
    editBtn.dataset.tip = "Browse and edit this worker's files in the hub editor";
    editBtn.onclick = () => _openRegistryEditor("worker", item._folder || wname, title);
    btnRow.appendChild(editBtn);

    const taskBtn = el("button", "btn btn-secondary btn-sm", "⚡ Agent Task");
    taskBtn.dataset.tip = "Create an agent task scoped to this worker — modify, extend, or debug it";
    taskBtn.onclick = () => _openAgentTaskModal({
      context_type: "worker", context_id: wname, context_label: title,
    });
    btnRow.appendChild(taskBtn);

    const delBtn = el("button", "btn btn-danger btn-sm", "✕");
    delBtn.dataset.tip = "Permanently delete this worker and all its files";
    delBtn.onclick = async () => {
      if (!confirm(`Delete worker "${title}"? This cannot be undone.`)) return;
      try { await api.workers.delete(wname); loadWorkers(); }
      catch (err) { alert("Delete failed: " + err.message); }
    };
    btnRow.appendChild(delBtn);

    card.appendChild(btnRow);
    el_.appendChild(card);
  }
}

// ── Package manager ────────────────────────────────────────────────────────

async function loadPackages() {
  const noticeEl  = document.getElementById("pkgBuildNotice");
  const declaredEl = document.getElementById("pkgDeclaredList");
  if (!noticeEl || !declaredEl) return;

  let data;
  try { data = await fetch("/api/packages/").then(r => r.json()); }
  catch { declaredEl.innerHTML = '<div class="empty-state">Could not load package data.</div>'; return; }

  // Build-type notice
  const notices = {
    frozen: `<div class="pkg-notice warning" data-tip="Bundled builds cannot install packages at runtime">
               ⚠ Running as a bundled application — pip install is not available.
               Use the <strong>Docker :workers</strong> image or run from source to manage packages.
             </div>`,
    docker: `<div class="pkg-notice info" data-tip="Packages installed here persist only in this container layer — rebuild the image to make them permanent">
               ℹ Docker container — pip installs are ephemeral unless you rebuild the image.
               Use the <strong>:workers</strong> image variant to pre-install worker dependencies.
             </div>`,
    source: "",
  };
  noticeEl.innerHTML = notices[data.build_type] || "";
  noticeEl.classList.toggle("hidden", !notices[data.build_type]);

  // Declared deps table
  const rows = [...(data.python || []), ...(data.system || [])];
  if (!rows.length) {
    declaredEl.innerHTML = '<div class="empty-state">No dependencies declared in worker.yaml files yet.</div>';
    return;
  }

  const table = document.createElement("table");
  table.className = "pkg-table";
  table.innerHTML = `<thead><tr>
    <th data-tip="Package name">Package</th>
    <th data-tip="Package type — python (pip) or system (OS binary)">Type</th>
    <th data-tip="Minimum version required by the worker">Required</th>
    <th data-tip="Currently installed version, or missing">Status</th>
    <th data-tip="Workers that depend on this package">Used by</th>
    <th data-tip="Notes and warnings about this dependency">Notes</th>
    <th></th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");

  for (const dep of rows) {
    const tr = document.createElement("tr");
    const isPython = dep.type === "python";
    const isSystem = dep.type === "system";
    const ok = dep.installed;

    let statusBadge = ok
      ? `<span class="pkg-badge ok" data-tip="Installed: ${dep.version_installed || ""}">✓ ${dep.version_installed || "ok"}</span>`
      : `<span class="pkg-badge missing" data-tip="Not installed">✗ missing</span>`;

    let notesHtml = dep.note ? `<span style="font-size:11px;color:var(--color-text-muted)">${dep.note}</span>` : "";
    if (isSystem && dep.shared_risk === "high") {
      notesHtml += `<br><span class="pkg-badge warn" data-tip="This system binary may be used by other applications — ESPAI does not manage its removal">⚠ shared system dep</span>`;
    }
    if (isSystem && dep.install_hint) {
      notesHtml += `<br><code style="font-size:10px;opacity:.7">${dep.install_hint}</code>`;
    }

    let actionHtml = "";
    if (isPython && data.can_install) {
      if (!ok) {
        actionHtml = `<button class="btn btn-primary btn-sm pkg-install-btn"
          data-name="${dep.name}" data-version="${dep.version || ""}"
          data-tip="pip install ${dep.name}${dep.version || ""}">Install</button>`;
      } else {
        actionHtml = `<button class="btn btn-secondary btn-sm pkg-remove-btn"
          data-name="${dep.name}"
          data-tip="pip uninstall ${dep.name}">Remove</button>`;
      }
    } else if (isSystem) {
      actionHtml = `<span style="font-size:11px;color:var(--color-text-muted)"
        data-tip="System packages are managed by your OS package manager">OS-managed</span>`;
    } else if (!data.can_install) {
      actionHtml = `<span style="font-size:11px;color:var(--color-text-muted)"
        data-tip="Not available in this build type">—</span>`;
    }

    tr.innerHTML = `
      <td><strong>${dep.name}</strong></td>
      <td><span class="pkg-type-badge ${dep.type}" data-tip="${isPython ? "Python pip package" : "System binary / external tool"}">${dep.type}</span></td>
      <td style="font-size:11px;font-family:monospace">${dep.version || "any"}</td>
      <td>${statusBadge}</td>
      <td style="font-size:11px;color:var(--color-text-muted)">${(dep.workers || []).join(", ")}</td>
      <td>${notesHtml}</td>
      <td>${actionHtml}</td>
    `;
    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  declaredEl.innerHTML = "";
  declaredEl.appendChild(table);

  // Wire install/remove buttons
  declaredEl.querySelectorAll(".pkg-install-btn").forEach(btn => {
    btn.onclick = () => _pkgInstall(btn.dataset.name, btn.dataset.version);
  });
  declaredEl.querySelectorAll(".pkg-remove-btn").forEach(btn => {
    btn.onclick = () => _pkgRemove(btn.dataset.name);
  });
}

async function _pkgInstall(name, version) {
  const spec = `${name}${version || ""}`;
  if (!confirm(`Install ${spec}?`)) return;
  try {
    const r = await fetch("/api/packages/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, version: version || "" }),
    });
    const d = await r.json();
    if (!r.ok) { alert(`Install failed: ${d.detail || d.error}`); return; }
    loadPackages();
  } catch (e) { alert("Install failed: " + e.message); }
}

async function _pkgRemove(name) {
  if (!confirm(`Remove ${name}? Workers that depend on it will fail until reinstalled.`)) return;
  try {
    const r = await fetch(`/api/packages/${encodeURIComponent(name)}`, { method: "DELETE" });
    const d = await r.json();
    if (!r.ok) { alert(`Remove failed: ${d.detail || d.error}`); return; }
    loadPackages();
  } catch (e) { alert("Remove failed: " + e.message); }
}

function _initPackageSearch() {
  const input     = document.getElementById("pkgSearchInput");
  const btn       = document.getElementById("btnPkgSearch");
  const resultEl  = document.getElementById("pkgSearchResult");
  if (!btn) return;

  async function doSearch() {
    const name = input.value.trim();
    if (!name) return;
    resultEl.innerHTML = '<span style="color:var(--color-text-muted);font-size:12px">Looking up…</span>';
    try {
      const r = await fetch("/api/packages/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const d = await r.json();
      if (!d.found) {
        resultEl.innerHTML = `<span style="color:var(--color-error);font-size:12px">Package "${name}" not found on PyPI.</span>`;
        return;
      }
      resultEl.innerHTML = `
        <div class="pkg-search-card">
          <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">
            <strong>${d.name}</strong>
            <span style="font-size:11px;font-family:monospace;color:var(--color-accent)">${d.version}</span>
            ${d.license ? `<span style="font-size:11px;color:var(--color-text-muted)">${d.license}</span>` : ""}
          </div>
          <p style="font-size:12px;color:var(--color-text-muted);margin:6px 0 8px">${d.summary || ""}</p>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <select id="pkgVersionSelect" style="font-size:12px;padding:3px 6px">
              ${(d.versions || []).map(v => `<option value="==${v}">${v}</option>`).join("")}
            </select>
            <button class="btn btn-primary btn-sm" id="btnPkgInstallSearch"
                    data-name="${d.name}"
                    data-tip="Install ${d.name} from PyPI">Install</button>
            ${d.home_page ? `<a href="${d.home_page}" target="_blank" rel="noopener"
              style="font-size:11px;color:var(--color-accent)" data-tip="Open package homepage">PyPI ↗</a>` : ""}
          </div>
          ${d.requires_python ? `<div style="font-size:10px;color:var(--color-text-muted);margin-top:6px">Requires Python ${d.requires_python}</div>` : ""}
        </div>`;
      document.getElementById("btnPkgInstallSearch").onclick = () => {
        const ver = document.getElementById("pkgVersionSelect").value;
        _pkgInstall(d.name, ver);
      };
    } catch (e) {
      resultEl.innerHTML = `<span style="color:var(--color-error);font-size:12px">Search failed: ${e.message}</span>`;
    }
  }

  btn.onclick = doSearch;
  input.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });
}

function _initShowInstalled() {
  const btn = document.getElementById("btnShowInstalled");
  const listEl = document.getElementById("pkgInstalledList");
  if (!btn) return;
  let shown = false;
  btn.onclick = async () => {
    if (shown) { listEl.classList.add("hidden"); listEl.innerHTML = ""; shown = false; btn.textContent = "Show all"; return; }
    btn.textContent = "Loading…";
    try {
      const r = await fetch("/api/packages/installed");
      const d = await r.json();
      const pkgs = (d.packages || []).sort((a, b) => a.name.localeCompare(b.name));
      listEl.innerHTML = `<div class="pkg-installed-grid">${
        pkgs.map(p => `<div class="pkg-installed-item" data-tip="${p.name} ${p.version}">
          <span style="font-weight:600;font-size:12px">${p.name}</span>
          <span style="font-family:monospace;font-size:11px;color:var(--color-text-muted)">${p.version}</span>
          <button class="btn btn-danger btn-sm pkg-remove-btn" data-name="${p.name}"
            data-tip="pip uninstall ${p.name}" style="padding:1px 6px;font-size:10px">✕</button>
        </div>`).join("")
      }</div>`;
      listEl.querySelectorAll(".pkg-remove-btn").forEach(b => {
        b.onclick = () => _pkgRemove(b.dataset.name);
      });
      listEl.classList.remove("hidden");
      shown = true;
      btn.textContent = "Hide";
    } catch (e) { btn.textContent = "Show all"; }
  };
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
  const el_ = document.getElementById("cardList");
  if (!items.length) { el_.innerHTML = '<div class="empty-state">Nothing found.</div>'; return; }
  el_.innerHTML = "";
  for (const item of items) {
    const cname = item.name || item._folder;
    const title = item.display_name || cname || "—";
    const sub   = item.category || "";
    const src   = item.event_source?.type || "";
    const tags  = [
      ...(item.compatible_boards || []).map(b => `<span class="tag">${b}</span>`),
      src ? `<span class="tag accent" data-tip="Data source type">${src}</span>` : "",
    ].slice(0, 5).join("");

    const card = el("div", "reg-card");
    card.innerHTML = `
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px">
        <div class="reg-card-title">${title}</div>
        ${_packBadge(item)}
      </div>
      ${sub ? `<div class="reg-card-sub">${sub}</div>` : ""}
      <div class="tag-row">${tags}</div>
    `;

    const btnRow = el("div", "");
    btnRow.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;margin-top:10px";

    const previewBtn = el("button", "btn btn-secondary btn-sm", "👁 Preview");
    previewBtn.dataset.tip = `Preview ${title} with simulated data — no device required`;
    previewBtn.onclick = () => _openCardPreview(cname, title);
    btnRow.appendChild(previewBtn);

    const editBtn = el("button", "btn btn-secondary btn-sm", "📁 Edit");
    editBtn.dataset.tip = "Browse and edit this card's files in the hub editor";
    editBtn.onclick = () => _openRegistryEditor("card", item._folder || cname, title);
    btnRow.appendChild(editBtn);

    const delBtn = el("button", "btn btn-danger btn-sm", "✕");
    delBtn.dataset.tip = "Permanently delete this card and all its files";
    delBtn.onclick = async () => {
      if (!confirm(`Delete card "${title}"? This cannot be undone.`)) return;
      try { await api.cards.delete(cname); loadCards(); }
      catch (err) { alert("Delete failed: " + err.message); }
    };
    btnRow.appendChild(delBtn);

    card.appendChild(btnRow);
    el_.appendChild(card);
  }
}

function _openCardPreview(name, title) {
  const url = `/api/cards/${encodeURIComponent(name)}/preview`;
  openModal(`Preview — ${title}`, `
    <div style="border-radius:8px;overflow:hidden;background:#080c10">
      <iframe src="${url}" style="width:100%;height:460px;border:none;display:block"
              sandbox="allow-scripts allow-same-origin" title="Card preview" data-tip="Live card preview rendered in a sandboxed frame"></iframe>
    </div>
  `, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
}

// ── Registry item editor (Workers / Cards / Recipes) ───────────────────────
//
// All three registry types share the same two-panel UX:
//   List view  — shows file tree, "New File" button, back button
//   Edit view  — CodeMirror, Save / Delete file / Back-to-list
//
// _openRegistryEditor(type, itemName, displayName)  → shows file list
// _regEditorOpenFile(type, itemName, filePath)       → switches to editor
// ──────────────────────────────────────────────────────────────────────────

const _REG_API = {
  worker: api.workers,
  card:   api.cards,
  recipe: api.recipes,
};

let _regEditorCtx = null;  // { type, itemName, displayName }

function _regEditorListView(listViewId, detailViewId) {
  document.getElementById(listViewId)?.classList.remove("hidden");
  document.getElementById(detailViewId)?.classList.add("hidden");
}
function _regEditorDetailView(listViewId, detailViewId) {
  document.getElementById(listViewId)?.classList.add("hidden");
  document.getElementById(detailViewId)?.classList.remove("hidden");
}

async function _openRegistryEditor(type, itemName, displayName) {
  const listViewId   = `${type}-list-view`;
  const detailViewId = `${type}-detail-view`;
  const detailEl     = document.getElementById(detailViewId);
  if (!detailEl) return;

  _regEditorCtx = { type, itemName, displayName };

  // Fetch files
  let files = [];
  try {
    const res = await _REG_API[type].files(itemName);
    files = res.files || [];
  } catch (err) {
    alert("Could not load files: " + err.message);
    return;
  }

  // Render detail panel
  detailEl.innerHTML = "";

  const hdr = el("header", "view-header");
  hdr.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px">
      <button class="btn btn-secondary btn-sm" id="btnRegBack" data-tip="Return to ${type} list">← Back</button>
      <div>
        <h1 style="margin:0">${displayName}</h1>
        <div style="font-family:monospace;font-size:10px;color:var(--color-text-muted);margin-top:2px;letter-spacing:.06em">${type} · ${itemName}</div>
      </div>
    </div>
    <button class="btn btn-secondary btn-sm" id="btnRegNewFile" data-tip="Create a new file in this ${type}'s folder">＋ New File</button>`;
  detailEl.appendChild(hdr);

  const fileListEl = el("div", "file-list");
  fileListEl.id = "regEditorFileList";
  fileListEl.style.cssText = "margin-top:8px";

  if (!files.length) {
    fileListEl.innerHTML = '<div class="empty-state">No files yet.</div>';
  } else {
    for (const f of files) {
      const isBin = f.path.endsWith(".bin");
      const editable = !isBin && f.size_bytes <= 512 * 1024;
      const row = el("div", "file-row");
      row.innerHTML = `
        <span class="file-path" style="${editable ? "cursor:pointer" : ""}">${f.path}${isBin ? ' <span class="tag">BIN</span>' : ""}</span>
        <span class="file-size">${formatBytes(f.size_bytes)}</span>`;
      if (editable) {
        row.dataset.tip = `Click to edit ${f.path}`;
        row.onclick = () => _regEditorOpenFile(type, itemName, f.path);
      }
      fileListEl.appendChild(row);
    }
  }
  detailEl.appendChild(fileListEl);

  // Switch to detail
  _regEditorDetailView(listViewId, detailViewId);

  // Back button
  detailEl.querySelector("#btnRegBack").onclick = () => {
    _regEditorCtx = null;
    _regEditorListView(listViewId, detailViewId);
  };

  // New file button
  detailEl.querySelector("#btnRegNewFile").onclick = () => {
    openModal("New File", `
      <div class="form-field">
        <label data-tip="Relative path within the ${type} folder — e.g. utils/helpers.py">File path</label>
        <input type="text" id="regNewFilePath" placeholder="e.g. utils/helpers.py" style="width:100%">
      </div>
    `, [
      { label: "Create", cls: "btn btn-primary", action: async () => {
        const path = document.getElementById("regNewFilePath")?.value?.trim();
        if (!path) return;
        try {
          await _REG_API[type].createFile(itemName, path, "");
          closeModal();
          await _openRegistryEditor(type, itemName, displayName);
          _regEditorOpenFile(type, itemName, path);
        } catch (err) { alert("Create failed: " + err.message); }
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
    setTimeout(() => document.getElementById("regNewFilePath")?.focus(), 100);
  };
}

async function _regEditorOpenFile(type, itemName, filePath) {
  let content = "";
  try {
    const res = await _REG_API[type].readFile(itemName, filePath);
    content = res.content;
  } catch (err) {
    alert("Could not open file: " + err.message);
    return;
  }

  const displayName = _regEditorCtx?.displayName || itemName;

  openModal(`✎ ${filePath}`, `
    <div style="font-family:monospace;font-size:10px;color:var(--color-text-muted);margin-bottom:8px">
      ${type} / ${itemName} / ${filePath}
    </div>
    <div id="codeEditorHost" style="height:460px;border:1px solid var(--color-card-border);border-radius:6px;overflow:hidden;font-size:13px"></div>
    <div id="editorStatus" style="font-size:11px;color:var(--color-text-muted);margin-top:6px;min-height:16px"></div>
  `, [
    { label: "Save", cls: "btn btn-primary", action: async () => {
      if (!_activeEditor) return;
      try {
        await _REG_API[type].writeFile(itemName, filePath, _activeEditor.getValue());
        document.getElementById("editorStatus").textContent = "Saved ✓";
        setTimeout(async () => {
          closeModal();
          await _openRegistryEditor(type, itemName, displayName);
        }, 400);
      } catch (err) { alert("Save failed: " + err.message); }
    }},
    { label: "Delete File", cls: "btn btn-danger", action: async () => {
      if (!confirm(`Delete ${filePath}?`)) return;
      try {
        await _REG_API[type].deleteFile(itemName, filePath);
        closeModal();
        await _openRegistryEditor(type, itemName, displayName);
      } catch (err) { alert("Delete failed: " + err.message); }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: () => { _activeEditor = null; closeModal(); } },
  ], { wide: true });

  const host = document.getElementById("codeEditorHost");
  if (!host) return;
  if (typeof CodeMirror === "undefined") {
    host.innerHTML = `<textarea style="width:100%;height:100%;background:#111;color:#eee;font-family:monospace;font-size:13px;padding:10px;border:none;resize:none">${content.replace(/</g,"&lt;")}</textarea>`;
    _activeEditor = { getValue: () => host.querySelector("textarea").value };
    return;
  }
  _activeEditor = CodeMirror(host, {
    value: content,
    mode: _cmMode(filePath),
    theme: "dracula",
    lineNumbers: true,
    lineWrapping: true,
    indentUnit: 2,
    tabSize: 2,
    matchBrackets: true,
    autoCloseBrackets: true,
    extraKeys: { Tab: cm => cm.execCommand("insertSoftTab") },
  });
  _activeEditor.setSize("100%", "100%");
  setTimeout(() => _activeEditor.refresh(), 50);
}

function _openNewRegistryItemModal(type, onCreated) {
  const typeCap = type.charAt(0).toUpperCase() + type.slice(1);
  const catPlaceholder = type === "worker" ? "media.vision" : type === "card" ? "sensing" : "sensing.environmental";
  openModal(`New ${typeCap}`, `
    <div class="form-field">
      <label data-tip="Human-readable display name, e.g. 'My Sensor Worker'">Display Name</label>
      <input type="text" id="regNewName" placeholder="e.g. My Sensor Worker" style="width:100%">
    </div>
    <div class="form-field" style="margin-top:10px">
      <label data-tip="URL-safe identifier — lowercase letters, digits, hyphens. Becomes the folder name.">Slug / Folder Name</label>
      <input type="text" id="regNewSlug" placeholder="e.g. my-sensor-worker" style="width:100%">
      <div id="regSlugPreview" style="font-size:11px;color:var(--color-text-muted);margin-top:4px;font-family:monospace"></div>
    </div>
    <div class="form-field" style="margin-top:10px">
      <label data-tip="Category for grouping in the registry, e.g. media.vision or sensing.environmental">Category</label>
      <input type="text" id="regNewCategory" placeholder="${catPlaceholder}" style="width:100%">
    </div>
    <div class="form-field" style="margin-top:10px">
      <label data-tip="One-line description shown in the registry grid">Description (optional)</label>
      <input type="text" id="regNewDesc" placeholder="" style="width:100%">
    </div>
  `, [
    { label: `Create ${typeCap}`, cls: "btn btn-primary", action: async () => {
      const name = document.getElementById("regNewName")?.value?.trim();
      const slug = document.getElementById("regNewSlug")?.value?.trim();
      const cat  = document.getElementById("regNewCategory")?.value?.trim() || "general";
      const desc = document.getElementById("regNewDesc")?.value?.trim() || "";
      if (!name || !slug) { alert("Name and slug are required."); return; }
      try {
        await _REG_API[type].create({ name, slug, category: cat, description: desc });
        closeModal();
        if (onCreated) onCreated(slug, name);
      } catch (err) { alert("Create failed: " + err.message); }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ]);
  // Auto-slug from name
  setTimeout(() => {
    const nameEl = document.getElementById("regNewName");
    const slugEl = document.getElementById("regNewSlug");
    const prev   = document.getElementById("regSlugPreview");
    const toSlug = s => s.toLowerCase().replace(/[\s_]+/g, "-").replace(/[^a-z0-9\-]/g, "").replace(/-{2,}/g, "-").replace(/^-+|-+$/g, "");
    nameEl?.addEventListener("input", () => {
      const s = toSlug(nameEl.value);
      slugEl.value = s;
      if (prev) prev.textContent = s ? `→ folder: ${type}s/${s}/` : "";
    });
    slugEl?.addEventListener("input", () => {
      if (prev) prev.textContent = slugEl.value ? `→ folder: ${type}s/${slugEl.value}/` : "";
    });
    nameEl?.focus();
  }, 100);
}

// Wire New buttons
document.getElementById("btnNewWorker").onclick = () =>
  _openNewRegistryItemModal("worker", (slug, name) => {
    loadWorkers();
    setTimeout(() => _openRegistryEditor("worker", slug, name), 300);
  });

// Wire package section controls (runs once on page load)
document.getElementById("btnRefreshPackages")?.addEventListener("click", loadPackages);
_initPackageSearch();
_initShowInstalled();
document.getElementById("btnNewCard").onclick = () =>
  _openNewRegistryItemModal("card", (slug, name) => {
    loadCards();
    setTimeout(() => _openRegistryEditor("card", slug, name), 300);
  });
document.getElementById("btnNewRecipe").onclick = () =>
  _openNewRegistryItemModal("recipe", (slug, name) => {
    loadRecipes();
    setTimeout(() => _openRegistryEditor("recipe", slug, name), 300);
  });

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
      const fwId = fw._folder || `${fw.board}-${fw.version}`;
      const displayTitle = fw.label || `${fw.board} — v${fw.version}`;
      const displaySub   = fw.label ? `${fw.board} — v${fw.version} · ${fw.channel} · ${formatBytes(fw.size_bytes)}`
                                    : `Channel: ${fw.channel} · ${formatBytes(fw.size_bytes)}`;
      card.innerHTML = `
        <div class="reg-card-title" style="display:flex;align-items:center;gap:6px">
          <span class="fw-label-text" data-tip="Click to rename this firmware entry">${displayTitle}</span>
          <button class="fw-label-edit" data-tip="Rename this firmware entry" style="background:none;border:none;cursor:pointer;color:var(--color-text-muted);font-size:11px;padding:0 2px">✎</button>
        </div>
        <div class="reg-card-sub">${displaySub}${fw.project_id ? ` · <span style="color:var(--color-accent);font-size:10px">📁 ${fw.project_id.slice(0,8)}</span>` : ""}</div>
        <div class="tag-row">
          <span class="tag" ${fw.sha256 ? `data-tip="Full SHA-256: ${fw.sha256}"` : ""}>${fw.sha256 ? fw.sha256.slice(0,12) + "…" : "no checksum"}</span>
          <span class="tag">${timeAgo(fw.uploaded)}</span>
          ${goodBadge}${rbBadge}
        </div>
      `;
      // Wire the rename (✎) button that's inside the card HTML
      const editLabelBtn = card.querySelector(".fw-label-edit");
      if (editLabelBtn) {
        editLabelBtn.onclick = () => {
          const current = fw.label || `${fw.board}-${fw.version}`;
          openModal("Rename Firmware Entry", `
            <div class="form-field">
              <label data-tip="Display name shown in the catalog and project firmware sections">Label</label>
              <input type="text" id="fwNewLabel" value="${current}" placeholder="e.g. Jingle Bells v1.2.0">
            </div>
          `, [
            { label: "Save", cls: "btn btn-primary", action: async () => {
              const label = document.getElementById("fwNewLabel").value.trim();
              if (!label) return;
              try {
                await api.ota.patchEntry(fwId, { label });
                closeModal();
                loadOTA();
              } catch (err) { alert("Error: " + err.message); }
            }},
            { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
          ]);
          setTimeout(() => { const el = document.getElementById("fwNewLabel"); el?.focus(); el?.select(); }, 50);
        };
      }

      const btnRow = el("div", "");
      btnRow.style.cssText = "display:flex;gap:6px;margin-top:10px;flex-wrap:wrap";

      const pushBtn = el("button", "btn btn-primary btn-sm", "⬆ Flash to Device");
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

// deviceFilter: optional array of device IDs to restrict the target selector to.
// If exactly one device results, skips the selection step entirely.
async function openPushModal(fw, deviceFilter = null) {
  const devices = await api.devices.list().catch(() => []);
  let paired = devices.filter(d => d.paired);
  if (deviceFilter && deviceFilter.length) {
    const filterSet = new Set(deviceFilter);
    const scoped = paired.filter(d => filterSet.has(d.id));
    if (scoped.length) paired = scoped;
  }
  if (!paired.length) {
    openModal("No Paired Devices",
      '<div class="empty-state">No paired devices available. Use 📡 Find Device in the project to pair one.</div>',
      [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
    return;
  }
  const pushTitle = fw.label || `${fw.board} v${fw.version}`;

  // One device → skip selection, go straight to confirm
  if (paired.length === 1) {
    const d = paired[0];
    const boardMismatch = fw.board && d.board && fw.board !== d.board;
    openModal(`Flash ${pushTitle} → ${d.name || d.id}`, `
      <p style="font-size:13px;margin-bottom:12px">
        Flash <strong>${pushTitle}</strong> to <strong>${d.name || d.id}</strong> (${d.board || "?"}) over WiFi?
      </p>
      ${boardMismatch ? `<p style="color:var(--color-warning);font-size:12px">⚠ Board mismatch: firmware targets <strong>${fw.board}</strong></p>` : ""}
      <p style="font-size:11px;color:var(--color-text-muted)">${formatBytes(fw.size_bytes)} · SHA-256: ${fw.sha256 ? fw.sha256.slice(0,16) + "…" : "—"}</p>
    `, [
      { label: "⬆ Flash Now", cls: "btn btn-primary", action: async () => {
        try {
          const result = await api.ota.push({ device_id: d.id, firmware_id: fw._folder, operator: "local" });
          closeModal();
          openModal(result.status === "ok" ? "Flash Successful ✓" : "Flash Failed",
            `<p>Status: <strong style="color:${result.status === "ok" ? "var(--color-success)" : "var(--color-danger)"}">${result.status}</strong></p>
             ${result.response ? `<pre style="font-size:11px;margin-top:8px;overflow:auto;max-height:120px">${result.response}</pre>` : ""}`,
            [{ label: "Close", cls: "btn btn-primary", action: closeModal }]);
        } catch (err) { alert("Flash failed: " + err.message); }
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
    return;
  }

  const opts = paired.map(d =>
    `<option value="${d.id}" data-board="${d.board || ''}">${d.name || d.id} (${d.board || "unknown board"})</option>`
  ).join("");
  openModal(`Push Firmware — ${pushTitle}`, `
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
  await Promise.all([_loadThemeManager(), _loadTokenGrid()]);
}

async function _loadThemeManager() {
  const grid = document.getElementById("themeGrid");
  if (!grid) return;
  grid.innerHTML = '<div class="empty-state">Loading themes…</div>';

  const themes = await api.design.themes().catch(() => []);
  if (!themes.length) {
    grid.innerHTML = '<div class="empty-state">No themes found.</div>';
    return;
  }

  // Key color tokens to show as swatches — in palette order
  const SWATCH_KEYS = [
    "color.background", "color.surface", "color.card",
    "color.accent", "color.accent2", "color.warning",
    "color.success", "color.text",
  ];

  grid.innerHTML = "";
  for (const t of themes) {
    const tokens = t.tokens || {};
    const swatches = SWATCH_KEYS
      .filter(k => tokens[k])
      .map(k => `<div class="theme-palette-swatch" style="background:${tokens[k]}" data-tip="${k}: ${tokens[k]}"></div>`)
      .join("");

    const card = el("div", `theme-card${t.is_active ? " active" : ""}`);
    card.innerHTML = `
      <div class="theme-palette">${swatches}</div>
      <div class="theme-card-body">
        <div class="theme-card-name" data-tip="${t.display_name || t.name}">${t.display_name || t.name}</div>
        <div class="theme-card-meta">
          ${t.is_active ? '<span class="theme-active-badge">ACTIVE</span>' : ""}
          ${t._pack === "custom"
            ? '<span class="theme-builtin-badge" style="color:var(--color-accent2)" data-tip="Custom theme — stored in design/themes/custom/, not tracked in git">custom</span>'
            : '<span class="theme-builtin-badge" data-tip="Official theme — tracked in git">official</span>'}
        </div>
      </div>
      <div class="theme-card-actions">
        ${!t.is_active
          ? `<button class="btn btn-primary btn-sm theme-activate-btn" data-name="${t.name}"
               data-tip="Activate the ${t.display_name || t.name} theme for all hub views">Activate</button>`
          : `<button class="btn btn-secondary btn-sm" disabled
               data-tip="This theme is already active">Active ✓</button>`}
        ${!t.builtin
          ? `<button class="btn btn-danger btn-sm theme-delete-btn" data-name="${t.name}"
               data-tip="Permanently delete this theme from disk">Delete</button>`
          : ""}
      </div>`;
    grid.appendChild(card);
  }

  // Activate buttons
  grid.querySelectorAll(".theme-activate-btn").forEach(btn => {
    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = "Activating…";
      try {
        await api.design.setActive(btn.dataset.name);
        // Reload tokens so the live inspector reflects the change
        await _loadTokenGrid();
        await _loadThemeManager();
      } catch (err) {
        alert("Could not activate theme: " + err.message);
        btn.disabled = false;
        btn.textContent = "Activate";
      }
    };
  });

  // Delete buttons
  grid.querySelectorAll(".theme-delete-btn").forEach(btn => {
    btn.onclick = async () => {
      if (!confirm(`Delete theme "${btn.dataset.name}"? This cannot be undone.`)) return;
      try {
        await api.design.delete(btn.dataset.name);
        await _loadThemeManager();
      } catch (err) {
        alert("Delete failed: " + err.message);
      }
    };
  });
}

async function _loadTokenGrid() {
  const tokens = await api.design.tokens().catch(() => ({}));
  const grid = document.getElementById("tokenList");
  if (!grid) return;
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

document.getElementById("btnThemeRefresh").onclick = loadDesign;

document.getElementById("btnThemeCreate").onclick = async () => {
  const baseTokens = await api.design.tokens().catch(() => ({}));

  // All token keys — separate color from non-color
  const colorKeys  = Object.keys(baseTokens).filter(k => k.startsWith("color."));
  const otherKeys  = Object.keys(baseTokens).filter(k => !k.startsWith("color."));

  // Build color picker rows
  const colorRows = colorKeys.map(k => {
    const v = baseTokens[k] || "#000000";
    // Hex-only for <input type=color> — strip non-hex
    const hex = /^#[0-9a-fA-F]{6}$/.test(v) ? v : "#1a1a2e";
    return `
      <div class="token-row" style="gap:8px">
        <input type="color" id="tc_${k.replace(/\./g,'_')}" value="${hex}"
               style="width:36px;height:28px;padding:2px;border-radius:4px;border:1px solid var(--color-card-border);background:none;cursor:pointer">
        <span class="token-name" style="flex:1">${k}</span>
        <input type="text" id="tcv_${k.replace(/\./g,'_')}" value="${v}"
               style="width:90px;font-family:monospace;font-size:11px;background:var(--color-surface);border:1px solid var(--color-card-border);border-radius:4px;padding:2px 6px;color:var(--color-text)">
      </div>`;
  }).join("");

  const otherRows = otherKeys.map(k => `
    <div class="token-row" style="gap:8px">
      <span style="width:36px;flex-shrink:0"></span>
      <span class="token-name" style="flex:1">${k}</span>
      <input type="text" id="tcv_${k.replace(/\./g,'_')}" value="${baseTokens[k] || ""}"
             style="width:140px;font-family:monospace;font-size:11px;background:var(--color-surface);border:1px solid var(--color-card-border);border-radius:4px;padding:2px 6px;color:var(--color-text)">
    </div>`).join("");

  openModal("＋ Create Theme", `
    <div style="display:flex;gap:12px;margin-bottom:14px">
      <div class="form-field" style="flex:1">
        <label data-tip="Human-readable name shown in the theme manager">Display Name</label>
        <input type="text" id="tcDisplayName" placeholder="e.g. Midnight Forest" style="width:100%">
      </div>
      <div class="form-field" style="flex:1">
        <label data-tip="URL-safe folder name — lowercase, hyphens">Slug</label>
        <input type="text" id="tcSlug" placeholder="e.g. midnight-forest" style="width:100%">
      </div>
    </div>
    <div class="home-band-hd" style="margin-bottom:8px">
      <span class="home-band-label">Color Tokens</span>
      <span style="font-family:monospace;font-size:9px;color:var(--color-text-muted)">pick from palette or type any CSS color</span>
    </div>
    <div class="token-grid" id="tcColorGrid" style="margin-bottom:12px">${colorRows}</div>
    <details>
      <summary style="font-size:11px;color:var(--color-accent);cursor:pointer;font-family:monospace;letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px">Other Tokens</summary>
      <div class="token-grid" style="margin-top:8px">${otherRows}</div>
    </details>
  `, [
    { label: "Save Theme", cls: "btn btn-primary", action: async () => {
      const displayName = document.getElementById("tcDisplayName")?.value?.trim();
      const slug = document.getElementById("tcSlug")?.value?.trim();
      if (!displayName || !slug) { alert("Display name and slug are required."); return; }
      // Collect all token values
      const tokens = {};
      for (const k of [...colorKeys, ...otherKeys]) {
        const valEl = document.getElementById(`tcv_${k.replace(/\./g,'_')}`);
        if (valEl) tokens[k] = valEl.value.trim();
      }
      try {
        await api.design.create({ slug, display_name: displayName, tokens });
        closeModal();
        loadDesign();
      } catch (err) { alert("Create failed: " + err.message); }
    }},
    { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
  ], { wide: true });

  // Sync color pickers ↔ text inputs
  setTimeout(() => {
    for (const k of colorKeys) {
      const safe = k.replace(/\./g, "_");
      const picker = document.getElementById(`tc_${safe}`);
      const text   = document.getElementById(`tcv_${safe}`);
      if (!picker || !text) continue;
      picker.oninput = () => { text.value = picker.value; };
      text.oninput   = () => {
        const v = text.value.trim();
        if (/^#[0-9a-fA-F]{6}$/.test(v)) picker.value = v;
      };
    }
    // Auto-slug from display name
    const nameEl = document.getElementById("tcDisplayName");
    const slugEl = document.getElementById("tcSlug");
    const toSlug = s => s.toLowerCase().replace(/[\s_]+/g,"-").replace(/[^a-z0-9\-]/g,"").replace(/-{2,}/g,"-").replace(/^-+|-+$/g,"");
    nameEl?.addEventListener("input", () => { if (!slugEl.value) slugEl.value = toSlug(nameEl.value); });
    nameEl?.focus();
  }, 60);
};

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
let _abTaskProjectMode = "dev"; // approval mode of the current task's project

function _abStatusClass(status) {
  return "ab-status-badge ab-status-" + (status || "draft");
}

function _abStatusLabel(status) {
  const labels = {
    draft:           "Draft",
    running:         "Live in Terminal",
    awaiting_review: "Ready to Review",
    approved:        "Done",
    rejected:        "Discarded",
    needs_changes:   "Needs Changes",
    merged:          "Merged",
    awaiting_input:  "Waiting for Paste",
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
    const delBtn = el("button", "btn btn-danger btn-sm", "✕");
    delBtn.dataset.tip = "Delete this task permanently";
    delBtn.style.cssText = "flex-shrink:0;margin-left:8px;padding:2px 8px";
    delBtn.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete task "${t.title}"? This cannot be undone.`)) return;
      await api.agentBench.deleteTask(t.id).catch(err => alert(err.message));
      _abLoadTaskList();
    };
    card.innerHTML = `
      <div class="ab-task-info">
        <div class="ab-task-title">${t.title}</div>
        <div class="ab-task-meta">${_AB_TEMPLATE_LABELS[t.template] || t.template} · ${t.lane} lane · ${timeAgo(t.updated)}${ctxBadge}${threadBadge}</div>
      </div>
      <span class="${_abStatusClass(t.status)}" data-tip="Task status: ${t.status}">${_abStatusLabel(t.status)}</span>
    `;
    card.style.cursor = "pointer";
    card.onclick = () => _abOpenTask(t.id);
    card.appendChild(delBtn);
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

  // Fetch project approval mode for this task
  const projId = task.context_id || task.project_id;
  _abTaskProjectMode = "dev";
  if (projId) {
    try { const { mode } = await api.projects.approvalMode(projId); _abTaskProjectMode = mode || "dev"; }
    catch (_) {}
  }

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
      const isError   = m.content.startsWith("ERROR:");
      const isStarted = m.content.startsWith("[") && m.content.includes("] Starting");
      const isPrompt  = m.content.startsWith("You are") || m.content.includes("## Task:");

      if (isError) {
        div.innerHTML = `
          <div style="color:var(--color-danger);font-size:12px;font-weight:700;margin-bottom:4px">&#x2715; Run Failed</div>
          <pre style="font-size:11px;white-space:pre-wrap;word-break:break-word;color:var(--color-danger);opacity:.85">${m.content.replace(/</g,"&lt;")}</pre>
        `;
      } else if (isStarted) {
        div.innerHTML = `<span style="font-size:12px;color:var(--color-text-muted);font-style:italic">&#x25B6; ${m.content.replace(/</g,"&lt;")}</span>`;
      } else if (isPrompt) {
        div.innerHTML = `
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
            <span style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--color-accent)">Prompt Generated</span>
            <button class="btn btn-secondary btn-sm" style="padding:3px 9px;font-size:11px">Copy Prompt</button>
            <button class="btn btn-secondary btn-sm" style="padding:3px 9px;font-size:11px">View Full</button>
          </div>
          <div style="font-size:12px;color:var(--color-text-muted);font-style:italic">The prompt is ready — copy it into Claude, ChatGPT, or another AI, apply the file changes it describes, then paste the response back below.</div>
        `;
        const [copyBtn, viewBtn] = div.querySelectorAll("button");
        copyBtn.onclick = () => {
          navigator.clipboard?.writeText(m.content).then(() => {
            const orig = copyBtn.textContent; copyBtn.textContent = "Copied!"; setTimeout(() => copyBtn.textContent = orig, 1500);
          }).catch(() => {});
        };
        viewBtn.onclick = () => openModal("Agent Prompt", `
          <pre style="font-size:11px;white-space:pre-wrap;word-break:break-word;max-height:400px;overflow:auto;line-height:1.5">${m.content.replace(/</g,"&lt;")}</pre>
        `, [
          { label: "Copy to Clipboard", cls: "btn btn-primary", action: () => {
            navigator.clipboard?.writeText(m.content).catch(() => {}); closeModal();
          }},
          { label: "Close", cls: "btn btn-secondary", action: closeModal },
        ]);
      } else {
        div.innerHTML = `<span style="font-size:12px;color:var(--color-text-muted)">${m.content.replace(/</g,"&lt;")}</span>`;
      }
    } else {
      div.textContent = m.content.slice(0, 4000) + (m.content.length > 4000 ? "\n…(truncated)" : "");
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
  const resetBtn    = document.getElementById("btnAbReset");

  const canRun      = ["draft", "needs_changes"].includes(task.status);
  const isStuck     = task.status === "running";
  const needsPaste  = task.status === "awaiting_review" && task.latest_run?.status === "awaiting_input";
  const needsReview = task.status === "awaiting_review" && !needsPaste;

  runPanel.style.display = canRun ? "" : "none";
  pastePanel.classList.toggle("hidden", !needsPaste);
  reviewPanel.classList.toggle("hidden", !needsReview);
  if (resetBtn) resetBtn.style.display = isStuck ? "" : "none";

  if (needsReview) _abApplyReviewMode(_abTaskProjectMode);

  if (adapterDesc) {
    const sel = document.getElementById("abAdapterSelect");
    adapterDesc.textContent = sel ? (_ADAPTER_DESCRIPTIONS[sel.value] || "") : "";
  }
}

function _abApplyReviewMode(mode) {
  const banner      = document.getElementById("abModeBanner");
  const heading     = document.getElementById("abReviewHeading");
  const hint        = document.getElementById("abReviewHint");
  const stableGate  = document.getElementById("abStableGate");
  const notesField  = document.getElementById("abNotesField");
  const approveBtn  = document.getElementById("btnAbApprove");
  const checkbox    = document.getElementById("abDiffAcknowledge");

  if (mode === "prototype") {
    banner.innerHTML = `<div class="ab-mode-banner ab-mode-prototype" data-tip="This project is in Prototype mode — minimal friction; changes ship fast">🚀 Prototype mode — fast path active</div>`;
    if (heading) heading.textContent = "Session Complete — Ship It?";
    if (hint) hint.textContent = "Prototype mode: no diff review required. Click Ship It to apply changes and continue.";
    if (stableGate) stableGate.classList.add("hidden");
    if (notesField) notesField.classList.add("hidden");
    if (approveBtn) { approveBtn.textContent = "✓ Ship It"; approveBtn.classList.add("ab-btn-prototype"); approveBtn.disabled = false; }

  } else if (mode === "stable") {
    banner.innerHTML = `<div class="ab-mode-banner ab-mode-stable" data-tip="This project is in Stable mode — review the diff before approving">🔒 Stable mode — review required</div>`;
    if (heading) heading.textContent = "Session Complete — Review Required";
    if (hint) hint.textContent = "Stable mode: view the diff before approving. Check the box below to confirm you've reviewed the changes.";
    if (stableGate) stableGate.classList.remove("hidden");
    if (notesField) notesField.classList.remove("hidden");
    if (approveBtn) { approveBtn.textContent = "✓ Mark Done"; approveBtn.disabled = !(checkbox?.checked); }
    if (checkbox) {
      checkbox.onchange = () => { if (approveBtn) approveBtn.disabled = !checkbox.checked; };
    }

  } else {
    // dev (default)
    banner.innerHTML = "";
    if (heading) heading.textContent = "Session Complete";
    if (hint) hint.textContent = "Claude finished the terminal session. View Diff to see what changed. If the changes look good and Claude committed, mark it Done. If you need more work, add notes and re-run.";
    if (stableGate) stableGate.classList.add("hidden");
    if (notesField) notesField.classList.remove("hidden");
    if (approveBtn) { approveBtn.textContent = "✓ Mark Done"; approveBtn.classList.remove("ab-btn-prototype"); approveBtn.disabled = false; }
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
    // Reload thread when session is live or just finished
    if (["running", "awaiting_review"].includes(task.status)) {
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

  document.getElementById("btnAbDelete").onclick = async () => {
    if (!_abCurrentTask) return;
    if (!confirm(`Delete task "${_abCurrentTask.title}"? This cannot be undone.`)) return;
    try {
      await api.agentBench.deleteTask(_abCurrentTask.id);
      document.getElementById("btnAbBack").click();
    } catch (err) { alert("Delete failed: " + err.message); }
  };

  document.getElementById("btnAbReset").onclick = async () => {
    if (!_abCurrentTask) return;
    try {
      await api.agentBench.resetTask(_abCurrentTask.id);
      const task = await api.agentBench.getTask(_abCurrentTask.id);
      _abCurrentTask = task;
      const statusEl = document.getElementById("abDetailStatus");
      if (statusEl) { statusEl.className = _abStatusClass(task.status); statusEl.textContent = _abStatusLabel(task.status); }
      _abUpdateRunControls(task);
    } catch (err) { alert("Reset failed: " + err.message); }
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
      const info      = typeof v === "object" ? v : { ready: v };
      const installed = info.installed ?? info.ready ?? false;
      const authed    = info.authenticated;  // undefined for non-claude adapters
      const ready     = info.ready ?? false;
      const hint      = !installed && info.install_hint
        ? `<div class="doctor-hint"><code>${info.install_hint}</code></div>` : "";

      let valText, valColor;
      if (!installed) {
        valText = "not installed"; valColor = "var(--color-danger)";
      } else if (authed === false) {
        valText = "not logged in"; valColor = "var(--color-warning)";
      } else {
        valText = "ready"; valColor = "var(--color-success)";
      }

      return `<div class="doctor-row" data-tool="${k}">
        <span class="doctor-icon ${ready ? "ok" : "miss"}">${ready ? "✓" : "✗"}</span>
        <span class="doctor-name">${k}</span>
        <span class="doctor-val" style="color:${valColor}">${valText}</span>
      </div>${hint}`;
    }).join("");

    const claudeInfo    = d.adapters_ready?.["claude-code-cli"] || {};
    const claudeInstalled = claudeInfo.installed ?? claudeInfo.ready ?? false;
    const claudeAuthed    = claudeInfo.authenticated ?? false;

    const authNote = claudeInstalled && !claudeAuthed
      ? `<p style="font-size:12px;color:var(--color-warning);margin-top:14px;line-height:1.6">
           ⚠ Claude Code is installed but <strong>not logged in</strong>.
           Click <strong>Login to Claude</strong> below — on Docker/headless, copy the URL shown and open it in your browser.
         </p>`
      : "";

    openModal("Agent Bench Doctor", `
      <p class="doctor-section-label">Tools</p>
      ${toolRows}
      <p class="doctor-section-label" style="margin-top:16px">Adapters</p>
      ${adapterRows}
      ${authNote}
    `, [
      ...(claudeInstalled ? [{
        label: claudeAuthed ? "Re-login to Claude" : "Login to Claude",
        cls: "btn btn-secondary",
        tip: claudeAuthed
          ? "Re-authenticate Claude Code CLI — opens a terminal with 'claude login'"
          : "Authenticate Claude Code CLI — opens a terminal with 'claude login'; on Docker copy the URL shown into your browser",
        action: () => {
          _hideDoctorTooltip(); closeModal();
          showView("terminal");
          setTimeout(async () => {
            try {
              const s = await api.terminal.create({ title: "Claude Login" });
              _termAttach(s.id, s.title);
              setTimeout(() => {
                if (_termSessions[s.id]?.ws?.readyState === 1)
                  _termSessions[s.id].ws.send("claude login\n");
              }, 800);
            } catch (_) {}
          }, 150);
        }
      }] : []),
      { label: "Close", cls: "btn btn-secondary", action: () => { _hideDoctorTooltip(); closeModal(); } },
    ]);

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
    let cfg = { enabled: true, allow_dev_device_deploy: false, require_human_review: true, allowed_adapters: ["manual"], claude_tool_mode: "full" };
    try { cfg = await api.agentBench.getConfig(); } catch (_) {}
    const mode = cfg.claude_tool_mode || "full";
    openModal("Agent Bench Settings", `
      <label style="display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:12px">
        <input type="checkbox" id="abSetEnabled" ${cfg.enabled ? "checked" : ""}
          data-tip="Enable or disable the Agent Bench feature entirely"> Enabled
      </label>
      <label style="display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:12px">
        <input type="checkbox" id="abSetReview" ${cfg.require_human_review ? "checked" : ""}
          data-tip="Require you to approve the diff before any changes are applied"> Require human review before merge
      </label>
      <label style="display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:12px">
        <input type="checkbox" id="abSetDevDeploy" ${cfg.allow_dev_device_deploy ? "checked" : ""}
          data-tip="Allow agent tasks to push firmware to dev-lane devices"> Allow dev device deployment
      </label>
      <div class="form-field">
        <label data-tip="Comma-separated list of adapter IDs Claude can use — e.g. manual, claude-code-cli">Allowed adapters</label>
        <input type="text" id="abSetAdapters" value="${(cfg.allowed_adapters || ["manual"]).join(",")}">
      </div>
      <div class="form-field" style="margin-top:14px">
        <label data-tip="Controls which tools Claude Code can use without asking for permission">Claude tool access</label>
        <div style="display:flex;flex-direction:column;gap:8px;margin-top:6px">
          <label style="display:flex;align-items:flex-start;gap:10px;font-size:13px;cursor:pointer">
            <input type="radio" name="abToolMode" value="full" ${mode === "full" ? "checked" : ""}
              style="margin-top:2px">
            <span>
              <strong>Full</strong> — shell commands, web access, file operations<br>
              <span style="font-size:11px;color:var(--color-text-muted)">Enables pio build, APK download/decompile, wget, pip, and other shell tools</span>
            </span>
          </label>
          <label style="display:flex;align-items:flex-start;gap:10px;font-size:13px;cursor:pointer">
            <input type="radio" name="abToolMode" value="safe" ${mode === "safe" ? "checked" : ""}
              style="margin-top:2px">
            <span>
              <strong>Safe</strong> — file read/write only, no shell or network<br>
              <span style="font-size:11px;color:var(--color-text-muted)">Claude can edit code but cannot run commands or download files</span>
            </span>
          </label>
        </div>
      </div>
      <p style="font-size:11px;color:var(--color-text-muted);margin-top:10px">Changes take effect on the next task run — no restart needed.</p>
    `, [
      { label: "Save", cls: "btn btn-primary", action: async () => {
        const enabled = document.getElementById("abSetEnabled").checked;
        const require_human_review = document.getElementById("abSetReview").checked;
        const allow_dev_device_deploy = document.getElementById("abSetDevDeploy").checked;
        const adaptersRaw = document.getElementById("abSetAdapters").value.trim();
        const allowed_adapters = adaptersRaw ? adaptersRaw.split(",").map(s => s.trim()).filter(Boolean) : ["manual"];
        const claude_tool_mode = document.querySelector('input[name="abToolMode"]:checked')?.value || "full";
        try {
          await api.agentBench.updateConfig({ enabled, require_human_review, allow_dev_device_deploy, allowed_adapters, claude_tool_mode });
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
    const isCLI = adapter_id !== "manual";

    // Check terminal availability now if we haven't visited the Terminal view yet.
    if (isCLI && _termAvailable === null) {
      try {
        const info = await api.terminal.available();
        _termAvailable = info.available;
      } catch (_) {
        _termAvailable = false;
      }
    }

    // CLI adapters: open a real interactive terminal session.
    // The backend writes the prompt to a temp file and pipes it to the CLI
    // so there are no shell-quoting issues with special characters.
    if (isCLI && _termAvailable) {
      try {
        // Ask the server to create the session — it handles prompt file + piping
        const s = await api.terminal.createAgent({
          task_id:    _abCurrentTask.id,
          adapter_id: adapter_id,
        });
        showView("terminal");
        await new Promise(r => setTimeout(r, 150));  // let view render
        _termAttach(s.id, s.title);

        const statusEl = document.getElementById("abDetailStatus");
        if (statusEl) { statusEl.className = _abStatusClass("running"); statusEl.textContent = "Running in Terminal"; }
      } catch (err) { alert("Could not open terminal session: " + err.message); }
      return;
    }

    // Manual adapter or terminal unavailable → original background flow
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
    const needsReview = _abCurrentTask.status === "awaiting_review";
    try {
      const { diffs, note } = await api.agentBench.getDiff(_abCurrentTask.id);
      if (!diffs.length) {
        const msg = note
          ? `<div class="empty-state" style="font-size:13px;line-height:1.6">${note}</div>`
          : '<div class="empty-state">No file changes recorded for the latest run.</div>';
        openModal("Diff", msg, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
        return;
      }

      // Build per-file diff blocks with Accept/Reject checkboxes
      const html = diffs.map((d, i) => {
        const lines = d.diff.split("\n").map(line => {
          const cls = line.startsWith("+") && !line.startsWith("+++") ? "add"
                    : line.startsWith("-") && !line.startsWith("---") ? "del"
                    : line.startsWith("@@") ? "hdr" : "ctx";
          return `<div class="ab-diff-line ${cls}">${line.replace(/</g,"&lt;").replace(/>/g,"&gt;")}</div>`;
        }).join("");
        const checkId = `diff_accept_${i}`;
        return `<div class="ab-diff-file" id="diff_file_${i}" style="margin-bottom:10px">
          <div class="ab-diff-file-header" style="display:flex;align-items:center;gap:10px">
            ${needsReview ? `<label style="display:flex;align-items:center;gap:5px;cursor:pointer;flex-shrink:0" data-tip="Check to keep this file change, uncheck to revert it">
              <input type="checkbox" id="${checkId}" checked style="width:14px;height:14px;accent-color:var(--color-accent)">
              <span style="font-family:monospace;font-size:9px;letter-spacing:.06em">KEEP</span>
            </label>` : ""}
            <span class="ab-diff-status-${d.status}">${d.status.toUpperCase()}</span>
            <span style="font-family:monospace;font-size:11px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${d.path}</span>
          </div>
          <div class="ab-diff-content">${lines}</div>
        </div>`;
      }).join("");

      const reviewButtons = needsReview ? [
        { label: "✓ Apply Selected", cls: "btn btn-primary", action: async () => {
          const rejectPaths = diffs
            .filter((_, i) => !document.getElementById(`diff_accept_${i}`)?.checked)
            .map(d => d.path);
          const notes = document.getElementById("abReviewNotes")?.value?.trim() || null;
          try {
            await api.agentBench.review(_abCurrentTask.id, {
              decision: "approved", notes, reject_paths: rejectPaths,
            });
            closeModal();
            const task = await api.agentBench.getTask(_abCurrentTask.id).catch(() => _abCurrentTask);
            _abCurrentTask = task;
            const statusEl = document.getElementById("abDetailStatus");
            if (statusEl) { statusEl.className = _abStatusClass(task.status); statusEl.textContent = _abStatusLabel(task.status); }
            _abUpdateRunControls(task);
          } catch (err) { alert("Review failed: " + err.message); }
        }},
        { label: "↩ Revert All", cls: "btn btn-secondary", action: async () => {
          if (!confirm("Revert ALL file changes from this run?")) return;
          const notes = document.getElementById("abReviewNotes")?.value?.trim() || null;
          try {
            await api.agentBench.review(_abCurrentTask.id, {
              decision: "needs_changes", notes, reject_paths: diffs.map(d => d.path),
            });
            closeModal();
            const task = await api.agentBench.getTask(_abCurrentTask.id).catch(() => _abCurrentTask);
            _abCurrentTask = task;
            _abUpdateRunControls(task);
          } catch (err) { alert("Revert failed: " + err.message); }
        }},
      ] : [];

      openModal(`Diff — ${diffs.length} file(s) changed`,
        `${needsReview ? '<p style="font-size:11px;color:var(--color-text-muted);margin-bottom:10px">Uncheck any file to revert that change. Click <strong>Apply Selected</strong> to approve the rest.</p>' : ""}
        <div style="max-height:460px;overflow-y:auto">${html}</div>`,
        [...reviewButtons, { label: "Close", cls: "btn btn-secondary", action: closeModal }],
        { wide: true },
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
      // After any approval, check if agent created/modified quarantined workers
      if (decision === "approved") {
        _checkQuarantineLift(task);
      }
    } catch (err) { alert("Error: " + err.message); }
  };

  async function _checkQuarantineLift(task) {
    const paths = JSON.parse(task.allowed_paths || "[]");
    const workerNames = paths
      .map(p => p.match(/^workers\/([^/]+)\/?$/)?.[1])
      .filter(Boolean);
    if (!workerNames.length) return;
    const workers = await api.workers.list().catch(() => []);
    const quarantined = workers.filter(w => workerNames.includes(w.name) && w.quarantine);
    if (!quarantined.length) return;
    openModal("Quarantined Workers Detected", `
      <p>The following worker(s) created or modified by this task are still <strong>quarantined</strong>:</p>
      <ul style="margin:10px 0 12px 18px">
        ${quarantined.map(w => `<li><strong>${w.name}</strong> — <code>workers/${w.name}/worker.yaml</code></li>`).join("")}
      </ul>
      <p style="font-size:13px">Quarantined workers can be tested but cannot run production jobs. Review the generated code, then lift quarantine to enable them.</p>
      <p style="font-size:12px;color:var(--color-text-muted);margin-top:8px">Lifting quarantine sets <code>quarantine: false, trusted: true</code> in the worker YAML.</p>
    `, [
      { label: "Lift Quarantine", cls: "btn btn-primary", action: async () => {
        try {
          for (const w of quarantined) {
            await api.workers.setQuarantine(w.name, false);
          }
          closeModal();
        } catch (err) { alert("Error: " + err.message); }
      }},
      { label: "Keep Quarantined", cls: "btn btn-secondary", action: closeModal },
    ]);
  }

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

  // Status filter buttons
  document.getElementById("abFilterRow").addEventListener("click", async (e) => {
    const btn = e.target.closest(".ab-filter");
    if (!btn) return;
    _abStatusFilter = btn.dataset.status;
    document.querySelectorAll(".ab-filter").forEach(b => b.classList.toggle("active", b === btn));
    await _abLoadTaskList();
  });

  // Context-type filter buttons
  let _abCtxFilter = "";
  document.getElementById("abContextFilterRow").addEventListener("click", async (e) => {
    const btn = e.target.closest(".ab-ctx-filter");
    if (!btn) return;
    _abCtxFilter = btn.dataset.ctx;
    document.querySelectorAll(".ab-ctx-filter").forEach(b => b.classList.toggle("active", b === btn));
    await _abLoadTaskList();
  });

  // Patch _abLoadTaskList: context filter + thread grouping
  _abLoadTaskList = async function () {
    const listEl = document.getElementById("abTaskList");
    listEl.innerHTML = '<div class="empty-state">Loading…</div>';
    const params = _abStatusFilter ? { status: _abStatusFilter } : {};
    let tasks = await api.agentBench.listTasks(params).catch(() => []);

    if (_abCtxFilter === "project")      tasks = tasks.filter(t => t.context_type === "project");
    else if (_abCtxFilter === "worker")  tasks = tasks.filter(t => t.context_type === "worker");
    else if (_abCtxFilter === "none")    tasks = tasks.filter(t => !t.context_type);

    if (!tasks.length) {
      listEl.innerHTML = '<div class="empty-state">No tasks match this filter.</div>';
      return;
    }

    // Thread grouping: separate roots from children
    const childMap = new Map();   // parent_id → [child, ...]
    const roots    = [];
    for (const t of tasks) {
      if (t.parent_task_id) {
        if (!childMap.has(t.parent_task_id)) childMap.set(t.parent_task_id, []);
        childMap.get(t.parent_task_id).push(t);
      } else {
        roots.push(t);
      }
    }

    listEl.innerHTML = "";

    const _makeTaskCard = (t, isChild = false) => {
      const card = el("div", "ab-task-card" + (isChild ? " ab-task-child" : ""));
      const ctxBadge = t.context_type
        ? `<span class="ab-context-badge" data-tip="Scoped to ${t.context_type}: ${t.context_id || ''}">${t.context_type === "project" ? "🗂" : "⚙"} ${(t.context_id || "").slice(0,10)}</span>`
        : (t.project_id ? `<span class="ab-context-badge" data-tip="Linked to project ${t.project_id.slice(0,8)}">🗂</span>` : "");
      const threadBadge = isChild ? `<span class="ab-thread-badge" data-tip="Follow-up in a task thread">↩ follow-up</span>` : "";
      const delBtn = el("button", "btn btn-danger btn-sm", "✕");
      delBtn.dataset.tip = "Delete this task permanently";
      delBtn.style.cssText = "flex-shrink:0;margin-left:8px;padding:2px 8px";
      delBtn.onclick = async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete task "${t.title}"? This cannot be undone.`)) return;
        await api.agentBench.deleteTask(t.id).catch(err => alert(err.message));
        _abLoadTaskList();
      };
      card.innerHTML = `
        <div class="ab-task-info">
          <div class="ab-task-title">${t.title}</div>
          <div class="ab-task-meta">${_AB_TEMPLATE_LABELS[t.template] || t.template} · ${t.lane} · ${timeAgo(t.updated)}${ctxBadge}${threadBadge}</div>
        </div>
        <span class="${_abStatusClass(t.status)}" data-tip="Task status: ${t.status}">${_abStatusLabel(t.status)}</span>
      `;
      card.style.cursor = "pointer";
      card.onclick = () => _abOpenTask(t.id);
      card.appendChild(delBtn);
      return card;
    };

    for (const root of roots) {
      const children = childMap.get(root.id) || [];

      if (!children.length) {
        listEl.appendChild(_makeTaskCard(root));
        continue;
      }

      // Render as collapsible thread group
      const group = el("div", "ab-thread-group");
      const rootCard = _makeTaskCard(root);

      // Toggle button for children
      const toggleBtn = el("button", "ab-thread-toggle", `▶ ${children.length} follow-up${children.length !== 1 ? "s" : ""}`);
      toggleBtn.dataset.tip = "Expand/collapse follow-up tasks in this thread";
      const childrenEl = el("div", "ab-thread-children hidden");
      for (const child of children) childrenEl.appendChild(_makeTaskCard(child, true));

      toggleBtn.onclick = (e) => {
        e.stopPropagation();
        const open = !childrenEl.classList.contains("hidden");
        childrenEl.classList.toggle("hidden", open);
        toggleBtn.textContent = open
          ? `▶ ${children.length} follow-up${children.length !== 1 ? "s" : ""}`
          : `▼ ${children.length} follow-up${children.length !== 1 ? "s" : ""}`;
      };

      rootCard.querySelector(".ab-task-info").appendChild(toggleBtn);
      group.appendChild(rootCard);
      group.appendChild(childrenEl);
      listEl.appendChild(group);
    }

    // Orphaned children (parent filtered out) shown flat
    for (const [pid, children] of childMap) {
      if (!roots.find(r => r.id === pid)) {
        for (const child of children) listEl.appendChild(_makeTaskCard(child, true));
      }
    }
  };
}

// ── Terminal view ──────────────────────────────────────────────────────────
//
// Each session is a real PTY on the hub server, bridged via WebSocket.
// Sessions persist until manually closed or the shell exits.
// Multiple sessions display as tabs; only one xterm instance is visible.
//
// Non-agent uses: pio build, git, pio device monitor, general shell, npm.
// Agent integration: CLI adapter "Run Task" opens a terminal session
//                   instead of the opaque background thread.

const _termSessions = {};   // { id: { title, ws, xterm, fitAddon, div } }
let   _termActiveId  = null;
let   _termAvailable = null;  // cached from /api/terminal/available

const _TERM_FONT_SIZE_KEY = "espai_term_font_size";

function _termFontSize() {
  return parseInt(localStorage.getItem(_TERM_FONT_SIZE_KEY) || "14");
}

async function loadTerminal() {
  // Check PTY availability once
  if (_termAvailable === null) {
    try {
      const info = await api.terminal.available();
      _termAvailable = info.available;
    } catch (_) {
      _termAvailable = false;
    }
  }

  const panel       = document.getElementById("termPanel");
  const unavailable = document.getElementById("termUnavailable");

  if (!_termAvailable) {
    panel?.classList.add("hidden");
    unavailable?.classList.remove("hidden");
    return;
  }

  unavailable?.classList.add("hidden");
  panel?.classList.remove("hidden");

  // Restore any sessions the server already knows about (page reload)
  try {
    const existing = await api.terminal.sessions();
    for (const s of existing) {
      if (!_termSessions[s.id]) _termAttach(s.id, s.title);
    }
  } catch (_) {}

  // Show welcome panel or terminal surface based on session state
  _termRenderTabs();
}

async function _termNewSession(opts = {}) {
  const { title, init_cmds, cwd } = opts;
  try {
    const s = await api.terminal.create({ title, init_cmds, cwd });
    _termAttach(s.id, s.title || title || "Shell");
    return s.id;
  } catch (err) {
    alert("Could not open terminal: " + err.message);
    return null;
  }
}

function _termAttach(sid, title) {
  if (_termSessions[sid]) { _termActivate(sid); return; }

  // Create xterm instance
  const xterm = new Terminal({
    fontFamily: "'Cascadia Code', 'Fira Code', 'Consolas', monospace",
    fontSize:    _termFontSize(),
    theme: {
      background:   "#0d0d0d",
      foreground:   "#eeddc4",
      cursor:       "#1aafc4",
      selectionBackground: "rgba(26,175,196,0.3)",
      black:        "#080c10",
      brightBlack:  "#3a4a5a",
      red:          "#e03248",
      brightRed:    "#e05060",
      green:        "#20bf96",
      brightGreen:  "#40dfb6",
      yellow:       "#f0a820",
      brightYellow: "#f8c840",
      blue:         "#1aafc4",
      brightBlue:   "#3acfe4",
      magenta:      "#c070e0",
      brightMagenta:"#e090ff",
      cyan:         "#1aafc4",
      brightCyan:   "#40cfe4",
      white:        "#eeddc4",
      brightWhite:  "#ffffff",
    },
    cursorBlink:  true,
    allowTransparency: false,
    scrollback:   5000,
  });

  const fitAddon = new FitAddon.FitAddon();
  xterm.loadAddon(fitAddon);

  // Create DOM container
  const surface = document.getElementById("termSurface");
  const div = document.createElement("div");
  div.className = "term-instance";
  div.dataset.sid = sid;
  surface.appendChild(div);
  xterm.open(div);

  // Connect WebSocket
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/api/terminal/ws/${sid}`);

  ws.onopen = () => {
    _termSessions[sid].wsReady = true;
    _termFit(sid);
  };

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === "output" || msg.type === "exit") {
        xterm.write(msg.data);
      }
    } catch (_) {
      xterm.write(e.data);
    }
  };

  ws.onclose = () => {
    const tab = document.querySelector(`.term-tab[data-sid="${sid}"] .term-tab-dot`);
    if (tab) tab.classList.add("disconnected");
  };

  xterm.onData(data => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "input", data }));
    }
  });

  xterm.onResize(({ cols, rows }) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "resize", cols, rows }));
    }
  });

  _termSessions[sid] = { title, ws, xterm, fitAddon, div };
  _termRenderTabs();
  _termActivate(sid);
}

function _termActivate(sid) {
  if (_termActiveId === sid) return;
  _termActiveId = sid;

  // Show correct instance, hide others
  document.querySelectorAll(".term-instance").forEach(d => {
    d.classList.toggle("active", d.dataset.sid === sid);
  });

  // Update tab highlight
  document.querySelectorAll(".term-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.sid === sid);
  });

  const closeBtn = document.getElementById("btnTermClose");
  if (closeBtn) closeBtn.style.display = sid ? "" : "none";

  // Fit after making visible
  requestAnimationFrame(() => _termFit(sid));
}

function _termFit(sid) {
  const s = _termSessions[sid];
  if (!s) return;
  try {
    s.fitAddon.fit();
    if (s.ws.readyState === WebSocket.OPEN) {
      const { cols, rows } = s.xterm;
      s.ws.send(JSON.stringify({ type: "resize", cols, rows }));
    }
  } catch (_) {}
}

function _termRenderTabs() {
  const tabs    = document.getElementById("termTabs");
  const welcome = document.getElementById("termWelcome");
  const surface = document.getElementById("termSurface");
  if (!tabs) return;

  tabs.innerHTML = "";
  const hasSessions = Object.keys(_termSessions).length > 0;

  // Show welcome when no sessions; show terminal surface when sessions exist
  if (welcome) welcome.style.display = hasSessions ? "none" : "block";
  if (surface) surface.style.display = hasSessions ? "block" : "none";

  for (const [sid, s] of Object.entries(_termSessions)) {
    const tab = el("div", `term-tab${sid === _termActiveId ? " active" : ""}`, `
      <span class="term-tab-dot"></span>
      <span>${s.title}</span>
    `);
    tab.dataset.sid = sid;
    tab.dataset.tip = `Session: ${s.title} — click to switch`;
    tab.onclick = () => _termActivate(sid);
    tabs.appendChild(tab);
  }
}

async function _termCloseActive() {
  const sid = _termActiveId;
  if (!sid) return;
  const s = _termSessions[sid];
  if (s) {
    s.ws.close();
    s.xterm.dispose();
    s.div.remove();
    delete _termSessions[sid];
  }
  try { await api.terminal.close(sid); } catch (_) {}
  _termActiveId = null;

  // Activate another session if any remain
  const remaining = Object.keys(_termSessions);
  if (remaining.length) {
    _termRenderTabs();
    _termActivate(remaining[remaining.length - 1]);
  } else {
    _termRenderTabs();
    const closeBtn = document.getElementById("btnTermClose");
    if (closeBtn) closeBtn.style.display = "none";
  }
}


// Wire terminal view buttons once DOM is ready
function _termWireEvents() {
  document.getElementById("btnTermShell")?.addEventListener("click", () =>
    _termNewSession({ title: "Shell" })
  );

  document.getElementById("btnTermMonitor")?.addEventListener("click", async () => {
    // Show device picker then open monitor
    const devices = await api.devices.list().catch(() => []);
    const paired  = devices.filter(d => d.paired);
    if (!paired.length) {
      openModal("No Paired Devices",
        '<div class="empty-state">Pair a device from Fleet view to use Serial Monitor.</div>',
        [{ label: "Go to Fleet", cls: "btn btn-primary", action: () => { closeModal(); showView("fleet"); } },
         { label: "Close", cls: "btn btn-secondary", action: closeModal }]);
      return;
    }
    const opts = paired.map(d =>
      `<option value="${d.id}">${d.name || d.id} (${d.board || "?"})</option>`
    ).join("");
    openModal("Serial Monitor", `
      <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:12px">Select a device — opens <code>pio device monitor</code> in a new terminal session.</p>
      <div class="form-field">
        <label>Device</label><select id="monDevSel">${opts}</select>
      </div>
      <div class="form-field">
        <label data-tip="Must match the device's firmware baud rate (usually 115200)">Baud rate</label>
        <input type="number" id="monBaud" value="115200" min="9600">
      </div>
    `, [
      { label: "Open Monitor", cls: "btn btn-primary", action: () => {
        const baud = document.getElementById("monBaud").value || "115200";
        closeModal();
        _termNewSession({ title: "Monitor", init_cmds: [`pio device monitor --baud ${baud}`] });
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
  });

  document.getElementById("btnTermBuild")?.addEventListener("click", async () => {
    const projects = await api.projects.list().catch(() => []);
    if (!projects.length) {
      openModal("No Projects",
        '<div class="empty-state">Create a project first, then use Build Firmware to compile it.</div>',
        [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
      return;
    }
    const opts = projects.map(p => `<option value="${p.id}">${p.name}</option>`).join("");
    openModal("Build Firmware", `
      <p style="font-size:13px;color:var(--color-text-muted);margin-bottom:12px">
        Opens a terminal in the project's <code>firmware/</code> directory and runs <code>pio run</code>.
      </p>
      <div class="form-field">
        <label>Project</label><select id="buildProjSel">${opts}</select>
      </div>
      <div class="form-field">
        <label data-tip="PlatformIO environment name — leave blank to use the default from platformio.ini">Environment (optional)</label>
        <input type="text" id="buildEnv" placeholder="e.g. esp32dev">
      </div>
    `, [
      { label: "Build", cls: "btn btn-primary", action: async () => {
        const pid  = document.getElementById("buildProjSel").value;
        const env  = document.getElementById("buildEnv").value.trim();
        const proj = await api.projects.files(pid).catch(() => null);
        const root = proj?.root ? proj.root.replace(/\\/g, "/") + "/firmware" : null;
        const cmd  = env ? `pio run -e ${env}` : "pio run";
        closeModal();
        _termNewSession({
          title:     projects.find(p => p.id === pid)?.name || "Build",
          cwd:       root || undefined,
          init_cmds: root ? [cmd] : [`echo "Navigate to firmware/ directory first"`, cmd],
        });
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
  });

  document.getElementById("btnTermSettings")?.addEventListener("click", () => {
    openModal("Terminal Settings", `
      <div class="form-field">
        <label data-tip="Adjust the font size in all terminal sessions">Font Size</label>
        <input type="number" id="termFontSize" value="${_termFontSize()}" min="8" max="24">
      </div>
    `, [
      { label: "Apply", cls: "btn btn-primary", action: () => {
        const size = parseInt(document.getElementById("termFontSize").value || "14");
        localStorage.setItem(_TERM_FONT_SIZE_KEY, String(size));
        for (const s of Object.values(_termSessions)) {
          try { s.xterm.options.fontSize = size; s.fitAddon.fit(); } catch (_) {}
        }
        closeModal();
      }},
      { label: "Cancel", cls: "btn btn-secondary", action: closeModal },
    ]);
  });

  document.getElementById("btnTermClose")?.addEventListener("click", () => _termCloseActive());

  // Quick-start command buttons in the welcome panel
  document.getElementById("termPanel")?.addEventListener("click", async (e) => {
    const btn = e.target.closest(".term-qstart-btn");
    if (!btn) return;
    const cmd = btn.dataset.cmd;
    if (!cmd) return;
    const sid = await _termNewSession({ title: cmd.split(" ")[0] });
    if (sid) {
      // Send the command after the shell is ready
      await new Promise(r => setTimeout(r, 500));
      const s = _termSessions[sid];
      if (s?.ws?.readyState === WebSocket.OPEN) {
        s.ws.send(JSON.stringify({ type: "input", data: cmd + "\r" }));
      }
    }
  });

  // Agent Bench link from welcome panel
  document.getElementById("btnTermGoAgentBench")?.addEventListener("click", () => showView("agent-bench"));

  // ? Help button — show shortcuts overlay
  document.getElementById("btnTermHelp")?.addEventListener("click", () => {
    openModal("Terminal — Keyboard Shortcuts", `
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <tr style="border-bottom:1px solid var(--color-card-border)"><td style="padding:7px 8px;width:130px"><kbd>Ctrl+C</kbd></td><td style="padding:7px 8px;color:var(--color-text-muted)">Interrupt / stop current command</td></tr>
        <tr style="border-bottom:1px solid var(--color-card-border)"><td style="padding:7px 8px"><kbd>Ctrl+L</kbd></td><td style="padding:7px 8px;color:var(--color-text-muted)">Clear the screen</td></tr>
        <tr style="border-bottom:1px solid var(--color-card-border)"><td style="padding:7px 8px"><kbd>Ctrl+D</kbd></td><td style="padding:7px 8px;color:var(--color-text-muted)">Send EOF / close the shell</td></tr>
        <tr style="border-bottom:1px solid var(--color-card-border)"><td style="padding:7px 8px"><kbd>↑</kbd> / <kbd>↓</kbd></td><td style="padding:7px 8px;color:var(--color-text-muted)">Navigate command history</td></tr>
        <tr style="border-bottom:1px solid var(--color-card-border)"><td style="padding:7px 8px"><kbd>Tab</kbd></td><td style="padding:7px 8px;color:var(--color-text-muted)">Autocomplete file and command names</td></tr>
        <tr style="border-bottom:1px solid var(--color-card-border)"><td style="padding:7px 8px"><kbd>Ctrl+A</kbd></td><td style="padding:7px 8px;color:var(--color-text-muted)">Jump to beginning of line</td></tr>
        <tr style="border-bottom:1px solid var(--color-card-border)"><td style="padding:7px 8px"><kbd>Ctrl+E</kbd></td><td style="padding:7px 8px;color:var(--color-text-muted)">Jump to end of line</td></tr>
        <tr style="border-bottom:1px solid var(--color-card-border)"><td style="padding:7px 8px"><kbd>Ctrl+K</kbd></td><td style="padding:7px 8px;color:var(--color-text-muted)">Delete from cursor to end of line</td></tr>
        <tr><td style="padding:7px 8px"><kbd>Ctrl+R</kbd></td><td style="padding:7px 8px;color:var(--color-text-muted)">Search command history</td></tr>
      </table>
      <p style="font-size:12px;color:var(--color-text-muted);margin-top:14px;line-height:1.7">
        <strong>Multiple sessions:</strong> Use <strong>+ Shell</strong> to open another tab.
        Sessions persist while you navigate other views — the shell keeps running in the background.
        <br><strong>Agent Bench:</strong> CLI adapter runs open here automatically.
      </p>
    `, [{ label: "Close", cls: "btn btn-secondary", action: closeModal }]);
  });

  // Refit when window resizes
  window.addEventListener("resize", () => {
    if (_termActiveId) _termFit(_termActiveId);
  });
}

// ── View router ────────────────────────────────────────────────────────────

const viewLoaders = {
  home:          loadHome,
  fleet:         loadFleet,   // kept for any direct link refs; not in nav
  projects:      loadProjects,
  recipes:       loadRecipes,
  workers:       () => { loadWorkers(); loadPackages(); },
  cards:         loadCards,
  jobs:          loadJobs,
  ota:           loadOTA,
  terminal:      loadTerminal,
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

const _MODAL_BTN_TIPS = {
  "close":          "Close this dialog",
  "cancel":         "Cancel and close without saving",
  "save":           "Save changes",
  "confirm":        "Confirm this action",
  "delete":         "Permanently delete — cannot be undone",
  "ok":             "Confirm",
  "copy link tag":  "Copy the HTML link tag to your clipboard",
  "done":           "Mark complete and close",
  "apply":          "Apply these settings",
  "submit":         "Submit",
};

function openModal(title, bodyHTML, buttons = [], opts = {}) {
  modalTitle.textContent  = title;
  modalBody.innerHTML     = bodyHTML;
  modalFooter.innerHTML   = "";
  for (const btn of buttons) {
    const b = el("button", btn.cls, btn.label);
    if (btn.dataset) Object.assign(b.dataset, btn.dataset);
    if (!b.dataset.tip)
      b.dataset.tip = btn.tip || _MODAL_BTN_TIPS[btn.label.toLowerCase()] || btn.label;
    b.onclick = btn.action;
    modalFooter.appendChild(b);
  }
  const modalEl = overlay.querySelector(".modal");
  if (modalEl) modalEl.classList.toggle("modal-wide", !!opts.wide);
  overlay.classList.remove("hidden");
}

function closeModal() {
  overlay.classList.add("hidden");
  modalBody.innerHTML = "";
  modalFooter.innerHTML = "";
  const modalEl = overlay.querySelector(".modal");
  if (modalEl) modalEl.classList.remove("modal-wide");
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
  _termWireEvents();

  // Mobile sidebar toggle
  const sidebar   = document.getElementById("sidebar");
  const hamburger = document.getElementById("btnHamburger");
  const overlay_  = document.getElementById("sidebarOverlay");
  function closeSidebar() {
    sidebar.classList.remove("open");
    if (overlay_) overlay_.classList.remove("active");
    if (hamburger) hamburger.classList.remove("nav-open");
  }
  function openSidebar() {
    sidebar.classList.add("open");
    if (overlay_) overlay_.classList.add("active");
    if (hamburger) hamburger.classList.add("nav-open");
  }
  hamburger?.addEventListener("click", openSidebar);
  overlay_?.addEventListener("click", closeSidebar);
  navItems.forEach(item => item.addEventListener("click", () => { if (window.innerWidth < 700) closeSidebar(); }));

  showView("home");
  setInterval(() => {
    const active = document.querySelector(".view.active");
    if (active?.id === "view-home")  loadHome();
    if (active?.id === "view-fleet") loadFleet();
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
