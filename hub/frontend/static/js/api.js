/* ESPAI Hub — API client
   Thin fetch wrapper. All calls return parsed JSON or throw an Error. */

const API_BASE = "";

async function apiFetch(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text}`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

const api = {
  status:   ()       => apiFetch("/api/status"),

  // Devices
  devices:  {
    list:           ()          => apiFetch("/api/devices/"),
    get:            (id)        => apiFetch(`/api/devices/${id}`),
    projects:       (id)        => apiFetch(`/api/devices/${encodeURIComponent(id)}/projects`),
    checkin:        (body)      => apiFetch("/api/devices/checkin",      { method: "POST", body: JSON.stringify(body) }),
    addManual:      (body)      => apiFetch("/api/devices/manual",       { method: "POST", body: JSON.stringify(body) }),
    initiatePair:   (id)        => apiFetch(`/api/devices/pair/initiate/${id}`, { method: "POST" }),
    confirmPair:    (body)      => apiFetch("/api/devices/pair/confirm", { method: "POST", body: JSON.stringify(body) }),
    delete:         (id)        => apiFetch(`/api/devices/${id}`,        { method: "DELETE" }),
    patch:  (id, body) => apiFetch(`/api/devices/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    scan:   (subnet) => apiFetch("/api/devices/scan" + (subnet ? `?subnet=${encodeURIComponent(subnet)}` : ""), { method: "POST" }),
    browse: (subnet) => apiFetch("/api/devices/browse" + (subnet ? `?subnet=${encodeURIComponent(subnet)}` : ""), { method: "POST" }),
    // Command channel
    sendCommand:    (id, body) => apiFetch(`/api/devices/${encodeURIComponent(id)}/commands`, { method: "POST", body: JSON.stringify(body) }),
    commands:       (id, status) => apiFetch(`/api/devices/${encodeURIComponent(id)}/commands${status ? "?status=" + status : ""}`),
    cancelCommand:  (id, cmdId) => apiFetch(`/api/devices/${encodeURIComponent(id)}/commands/${cmdId}`, { method: "DELETE" }),
  },

  // Projects
  projects: {
    list:       ()       => apiFetch("/api/projects/"),
    get:        (id)     => apiFetch(`/api/projects/${id}`),
    files:      (id)     => apiFetch(`/api/projects/${id}/files`),
    create:     (body)   => apiFetch("/api/projects/",        { method: "POST",   body: JSON.stringify(body) }),
    import:     (body)   => apiFetch("/api/projects/import",  { method: "POST",   body: JSON.stringify(body) }),
    update:      (id, b)  => apiFetch(`/api/projects/${id}`,              { method: "PATCH",  body: JSON.stringify(b) }),
    rename:      (id, b)  => apiFetch(`/api/projects/${id}/rename`,       { method: "PATCH",  body: JSON.stringify(b) }),
    delete:      (id)     => apiFetch(`/api/projects/${id}`,              { method: "DELETE" }),
    theme:       (id)     => apiFetch(`/api/projects/${id}/theme`),
    setTheme:    (id, b)  => apiFetch(`/api/projects/${id}/theme`,        { method: "PUT", body: JSON.stringify(b) }),
    importBuild: (id, ch) => apiFetch(`/api/projects/${id}/import-build${ch ? "?channel=" + ch : ""}`, { method: "POST" }),
    appUrl:           (id)     => apiFetch(`/api/projects/${id}/app-url`),
    regenerateContext: (id)      => apiFetch(`/api/projects/${id}/regenerate-context`, { method: "POST" }),
    applyHubTheme:     (id)      => apiFetch(`/api/projects/${id}/apply-hub-theme`,     { method: "POST" }),
    // Multi-node
    nodes:         (id)            => apiFetch(`/api/projects/${id}/nodes`),
    upsertNode:    (id, did, body) => apiFetch(`/api/projects/${id}/nodes/${encodeURIComponent(did)}`, { method: "PUT",    body: JSON.stringify(body) }),
    removeNode:    (id, did)       => apiFetch(`/api/projects/${id}/nodes/${encodeURIComponent(did)}`, { method: "DELETE" }),
    topology:      (id)            => apiFetch(`/api/projects/${id}/topology`),
    setTopology:   (id, body)      => apiFetch(`/api/projects/${id}/topology`,             { method: "PUT",    body: JSON.stringify(body) }),
    gitLog:            (id, n)   => apiFetch(`/api/projects/${id}/git/log${n ? "?limit=" + n : ""}`),
    gitRollback:       (id, sha) => apiFetch(`/api/projects/${id}/git/rollback`, { method: "POST", body: JSON.stringify({ sha }) }),
    approvalMode:      (id)      => apiFetch(`/api/projects/${id}/approval-mode`),
    setApprovalMode:   (id, mode)=> apiFetch(`/api/projects/${id}/approval-mode?mode=${encodeURIComponent(mode)}`, { method: "PUT" }),
    // File editor
    readFile:    (id, path)    => apiFetch(`/api/projects/${id}/files/${path}`),
    writeFile:   (id, path, c) => apiFetch(`/api/projects/${id}/files/${path}`, { method: "PUT",    body: JSON.stringify({ content: c }) }),
    createFile:  (id, path, c) => apiFetch(`/api/projects/${id}/files/${path}`, { method: "POST",   body: JSON.stringify({ content: c || "" }) }),
    deleteFile:  (id, path)    => apiFetch(`/api/projects/${id}/files/${path}`, { method: "DELETE" }),
    // Project data store
    dataLatest:  (id)             => apiFetch(`/api/projects/${id}/data/latest`),
    dataHistory: (id, params)     => {
      const q = new URLSearchParams(Object.fromEntries(Object.entries(params || {}).filter(([,v]) => v != null))).toString();
      return apiFetch(`/api/projects/${id}/data${q ? "?" + q : ""}`);
    },
    dataPush:      (id, body)     => apiFetch(`/api/projects/${id}/data`, { method: "POST", body: JSON.stringify(body) }),
    dataClear:     (id)           => apiFetch(`/api/projects/${id}/data`, { method: "DELETE" }),
    dataAggregate: (id, params)   => {
      const q = new URLSearchParams(Object.fromEntries(Object.entries(params || {}).filter(([,v]) => v != null))).toString();
      return apiFetch(`/api/projects/${id}/data/aggregate${q ? "?" + q : ""}`);
    },
    dataSpatial:   (id, params)   => {
      const q = new URLSearchParams(Object.fromEntries(Object.entries(params || {}).filter(([,v]) => v != null))).toString();
      return apiFetch(`/api/projects/${id}/data/spatial${q ? "?" + q : ""}`);
    },
    dataTrack:     (id, params)   => {
      const q = new URLSearchParams(Object.fromEntries(Object.entries(params || {}).filter(([,v]) => v != null))).toString();
      return apiFetch(`/api/projects/${id}/track${q ? "?" + q : ""}`);
    },
    geofenceCheck:  (id, body)    => apiFetch(`/api/projects/${id}/data/geofence-check`, { method: "POST", body: JSON.stringify(body) }),
    listGeofences:  (id)          => apiFetch(`/api/projects/${id}/geofences`),
    createGeofence: (id, body)    => apiFetch(`/api/projects/${id}/geofences`, { method: "POST", body: JSON.stringify(body) }),
    deleteGeofence: (id, gfId)    => apiFetch(`/api/projects/${id}/geofences/${gfId}`, { method: "DELETE" }),
    // Matter config
    getMatter:    (id)           => apiFetch(`/api/projects/${id}/matter`),
    setMatter:    (id, body)     => apiFetch(`/api/projects/${id}/matter`, { method: "PUT", body: JSON.stringify(body) }),
    // Media store
    listMedia:    (id, ct)       => apiFetch(`/api/projects/${id}/media${ct ? "?content_type=" + encodeURIComponent(ct) : ""}`),
    mediaUrl:     (id, fileId)   => `/api/projects/${id}/media/${fileId}`,
    deleteMedia:  (id, fileId)   => apiFetch(`/api/projects/${id}/media/${fileId}`, { method: "DELETE" }),
    mediaQuota:   (id)           => apiFetch(`/api/projects/${id}/media/quota`),
    uploadMedia:  (id, formData) => apiFetch(`/api/projects/${id}/media`, { method: "POST", body: formData, headers: {} }),
  },

  // Local Network Services
  services: {
    list:       ()          => apiFetch("/api/services/"),
    categories: ()          => apiFetch("/api/services/categories"),
    discover:   (subnet)    => apiFetch("/api/services/discover" + (subnet ? `?subnet=${encodeURIComponent(subnet)}` : ""), { method: "POST" }),
    add:        (body)      => apiFetch("/api/services/",        { method: "POST",   body: JSON.stringify(body) }),
    update:     (id, body)  => apiFetch(`/api/services/${id}`,  { method: "PATCH",  body: JSON.stringify(body) }),
    delete:     (id)        => apiFetch(`/api/services/${id}`,  { method: "DELETE" }),
  },

  // Caddy config
  caddy: {
    get:      () => apiFetch("/api/caddy/caddyfile"),
    write:    () => apiFetch("/api/caddy/write", { method: "POST" }),
    downloadUrl: () => "/api/caddy/download",
  },

  // Registry
  workers: {
    list:          ()         => apiFetch("/api/workers/"),
    get:           (n)        => apiFetch(`/api/workers/${n}`),
    create:        (body)     => apiFetch("/api/workers/new", { method: "POST", body: JSON.stringify(body) }),
    patch:         (n, body)  => apiFetch(`/api/workers/${encodeURIComponent(n)}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete:        (n)        => apiFetch(`/api/workers/${encodeURIComponent(n)}`, { method: "DELETE" }),
    test:          (n, body)  => apiFetch(`/api/workers/${encodeURIComponent(n)}/test`, { method: "POST", body: JSON.stringify(body) }),
    compat:        (n)        => apiFetch(`/api/workers/${encodeURIComponent(n)}/compat`),
    logs:          (n, lines) => apiFetch(`/api/workers/${encodeURIComponent(n)}/logs${lines ? "?lines=" + lines : ""}`),
    gitLog:        (n)        => apiFetch(`/api/workers/${encodeURIComponent(n)}/git/log`),
    gitRollback:   (n, sha)   => apiFetch(`/api/workers/${encodeURIComponent(n)}/git/rollback`, { method: "POST", body: JSON.stringify({ sha }) }),
    files:         (n)        => apiFetch(`/api/workers/${encodeURIComponent(n)}/files`),
    readFile:      (n, path)  => apiFetch(`/api/workers/${encodeURIComponent(n)}/files/${path}`),
    writeFile:     (n, path, c) => apiFetch(`/api/workers/${encodeURIComponent(n)}/files/${path}`, { method: "PUT",  body: JSON.stringify({ content: c }) }),
    createFile:    (n, path, c) => apiFetch(`/api/workers/${encodeURIComponent(n)}/files/${path}`, { method: "POST", body: JSON.stringify({ content: c || "" }) }),
    deleteFile:    (n, path)  => apiFetch(`/api/workers/${encodeURIComponent(n)}/files/${path}`, { method: "DELETE" }),
    serviceStatus: ()         => apiFetch("/api/workers/services/status"),
    serviceStart:  (n)        => apiFetch(`/api/workers/${encodeURIComponent(n)}/service/start`,   { method: "POST" }),
    serviceStop:   (n)        => apiFetch(`/api/workers/${encodeURIComponent(n)}/service/stop`,    { method: "POST" }),
    serviceRestart:(n)        => apiFetch(`/api/workers/${encodeURIComponent(n)}/service/restart`, { method: "POST" }),
  },
  recipes: {
    list:      ()      => apiFetch("/api/recipes/"),
    get:       (n)     => apiFetch(`/api/recipes/${n}`),
    create:    (body)  => apiFetch("/api/recipes/new", { method: "POST", body: JSON.stringify(body) }),
    delete:    (n)     => apiFetch(`/api/recipes/${encodeURIComponent(n)}`, { method: "DELETE" }),
    validate:  (n)     => apiFetch(`/api/recipes/${encodeURIComponent(n)}/validate`),
    export:    (n)     => apiFetch(`/api/recipes/${encodeURIComponent(n)}/export`),
    compat:    (n)     => apiFetch(`/api/recipes/${encodeURIComponent(n)}/compat`),
    files:     (n)     => apiFetch(`/api/recipes/${encodeURIComponent(n)}/files`),
    readFile:  (n, path)    => apiFetch(`/api/recipes/${encodeURIComponent(n)}/files/${path}`),
    writeFile: (n, path, c) => apiFetch(`/api/recipes/${encodeURIComponent(n)}/files/${path}`, { method: "PUT",  body: JSON.stringify({ content: c }) }),
    createFile:(n, path, c) => apiFetch(`/api/recipes/${encodeURIComponent(n)}/files/${path}`, { method: "POST", body: JSON.stringify({ content: c || "" }) }),
    deleteFile:(n, path)    => apiFetch(`/api/recipes/${encodeURIComponent(n)}/files/${path}`, { method: "DELETE" }),
  },
  cards: {
    list:       ()     => apiFetch("/api/cards/"),
    get:        (n)    => apiFetch(`/api/cards/${n}`),
    create:     (body) => apiFetch("/api/cards/new", { method: "POST", body: JSON.stringify(body) }),
    delete:     (n)    => apiFetch(`/api/cards/${encodeURIComponent(n)}`, { method: "DELETE" }),
    previewUrl: (n)    => `/api/cards/${encodeURIComponent(n)}/preview`,
    files:      (n)    => apiFetch(`/api/cards/${encodeURIComponent(n)}/files`),
    readFile:   (n, path)    => apiFetch(`/api/cards/${encodeURIComponent(n)}/files/${path}`),
    writeFile:  (n, path, c) => apiFetch(`/api/cards/${encodeURIComponent(n)}/files/${path}`, { method: "PUT",  body: JSON.stringify({ content: c }) }),
    createFile: (n, path, c) => apiFetch(`/api/cards/${encodeURIComponent(n)}/files/${path}`, { method: "POST", body: JSON.stringify({ content: c || "" }) }),
    deleteFile: (n, path)    => apiFetch(`/api/cards/${encodeURIComponent(n)}/files/${path}`, { method: "DELETE" }),
  },

  // Design
  design: {
    tokens:    ()      => apiFetch("/api/design/tokens"),
    themes:    ()      => apiFetch("/api/design/themes"),
    skins:     ()      => apiFetch("/api/design/skins"),
    active:    ()      => apiFetch("/api/design/theme/active"),
    setActive: (name)  => apiFetch("/api/design/theme/active", { method: "PUT", body: JSON.stringify({ theme: name }) }),
    create:    (body)  => apiFetch("/api/design/themes", { method: "POST", body: JSON.stringify(body) }),
    delete:    (name)  => apiFetch(`/api/design/themes/${encodeURIComponent(name)}`, { method: "DELETE" }),
  },

  // Jobs
  jobs: {
    list:   (status) => apiFetch(`/api/jobs/${status ? "?status=" + status : ""}`),
    submit: (body)   => apiFetch("/api/jobs/submit",   { method: "POST",   body: JSON.stringify(body) }),
    cancel: (id)     => apiFetch(`/api/jobs/${id}/cancel`, { method: "POST" }),
  },

  // OTA
  ota: {
    catalog:          ()        => apiFetch("/api/ota/catalog"),
    catalogByProject: (pid)     => apiFetch(`/api/ota/catalog/project/${encodeURIComponent(pid)}`),
    log:        (did)      => apiFetch(`/api/ota/log${did ? "?device_id=" + did : ""}`),
    push:       (body)     => apiFetch("/api/ota/push",      { method: "POST",   body: JSON.stringify(body) }),
    rollback:   (body)     => apiFetch("/api/ota/rollback",  { method: "POST",   body: JSON.stringify(body) }),
    markGood:   (id, op)   => apiFetch(`/api/ota/catalog/${encodeURIComponent(id)}/mark-good?operator=${encodeURIComponent(op || "local")}`, { method: "POST" }),
    patchEntry: (id, body) => apiFetch(`/api/ota/catalog/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
    upload: (file, board, version, channel, label, projectId) => {
      const fd = new FormData();
      fd.append("file", file);
      const p = new URLSearchParams({ board, version, channel });
      if (label)     p.set("label",      label);
      if (projectId) p.set("project_id", projectId);
      return fetch(`/api/ota/catalog/upload?${p}`, { method: "POST", body: fd }).then(async r => {
        if (!r.ok) { const t = await r.text().catch(() => r.statusText); throw new Error(`${r.status} ${t}`); }
        return r.json();
      });
    },
  },

  // Events
  events: {
    list:    (opts) => {
      const q = new URLSearchParams(opts || {}).toString();
      return apiFetch(`/api/events/${q ? "?" + q : ""}`);
    },
    publish: (body) => apiFetch("/api/events/publish", { method: "POST", body: JSON.stringify(body) }),
  },

  // Rules
  rules: {
    list:     ()           => apiFetch("/api/rules/"),
    get:      (id)         => apiFetch(`/api/rules/${id}`),
    create:   (body)       => apiFetch("/api/rules/",   { method: "POST",   body: JSON.stringify(body) }),
    update:   (id, body)   => apiFetch(`/api/rules/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete:   (id)         => apiFetch(`/api/rules/${id}`, { method: "DELETE" }),
    upcoming: (n)          => apiFetch(`/api/rules/upcoming${n ? "?limit=" + n : ""}`),
  },

  // Admin
  admin: {
    backup:   ()     => apiFetch("/api/admin/backup"),
    download: ()     => window.open("/api/admin/backup/download", "_blank"),
    restore:  (body) => apiFetch("/api/admin/restore", { method: "POST", body: JSON.stringify(body) }),
    status:   ()     => apiFetch("/api/admin/status"),
  },

  // Terminal
  terminal: {
    available:      ()      => apiFetch("/api/terminal/available"),
    sessions:       ()      => apiFetch("/api/terminal/sessions"),
    create:         (body)  => apiFetch("/api/terminal/sessions",               { method: "POST",   body: JSON.stringify(body) }),
    createAgent:    (body)  => apiFetch("/api/terminal/sessions/agent",         { method: "POST",   body: JSON.stringify(body) }),
    close:          (id)    => apiFetch(`/api/terminal/sessions/${id}`,         { method: "DELETE" }),
  },

  // Meta
  meta: () => apiFetch("/api/meta"),

  // OTA rollout
  otaRollout: (body) => apiFetch("/api/ota/rollout", { method: "POST", body: JSON.stringify(body) }),

  // Agent Bench
  agentBench: {
    getConfig:     ()           => apiFetch("/api/agent-bench/config"),
    listTemplates: (deviceType) => apiFetch(`/api/agent-bench/templates?device_type=${deviceType || "esp32"}`),
    updateConfig:  (body)       => apiFetch("/api/agent-bench/config",    { method: "POST", body: JSON.stringify(body) }),
    doctor:        ()           => apiFetch("/api/agent-bench/doctor"),
    listAdapters:  ()           => apiFetch("/api/agent-bench/adapters"),
    testAdapter:   (name)       => apiFetch(`/api/agent-bench/adapters/${encodeURIComponent(name)}/test`, { method: "POST" }),
    listTasks:     (params)     => {
      const q = new URLSearchParams(Object.fromEntries(Object.entries(params || {}).filter(([,v]) => v != null))).toString();
      return apiFetch(`/api/agent-bench/tasks${q ? "?" + q : ""}`);
    },
    createTask:    (body)       => apiFetch("/api/agent-bench/tasks",     { method: "POST", body: JSON.stringify(body) }),
    getTask:       (id)         => apiFetch(`/api/agent-bench/tasks/${id}`),
    getPrompt:     (id)         => apiFetch(`/api/agent-bench/tasks/${id}/prompt`),
    getMessages:   (id)         => apiFetch(`/api/agent-bench/tasks/${id}/messages`),
    addMessage:    (id, body)   => apiFetch(`/api/agent-bench/tasks/${id}/message`, { method: "POST", body: JSON.stringify(body) }),
    getDiff:       (id)         => apiFetch(`/api/agent-bench/tasks/${id}/diff`),
    getArtifacts:  (id)         => apiFetch(`/api/agent-bench/tasks/${id}/artifacts`),
    runTask:       (id, body)   => apiFetch(`/api/agent-bench/tasks/${id}/run`,     { method: "POST", body: JSON.stringify(body) }),
    review:        (id, body)   => apiFetch(`/api/agent-bench/tasks/${id}/review`,  { method: "POST", body: JSON.stringify(body) }),
    deleteTask:    (id)         => apiFetch(`/api/agent-bench/tasks/${id}`,         { method: "DELETE" }),
    resetTask:     (id)         => apiFetch(`/api/agent-bench/tasks/${id}/reset`,   { method: "POST" }),
    listRuns:      (taskId)     => apiFetch(`/api/agent-bench/runs${taskId ? "?task_id=" + taskId : ""}`),
    install:       (tool)       => apiFetch(`/api/agent-bench/install/${encodeURIComponent(tool)}`,   { method: "POST" }),
    uninstall:     (tool)       => apiFetch(`/api/agent-bench/uninstall/${encodeURIComponent(tool)}`, { method: "POST" }),
  },

  // Matter bridge
  matter: {
    status:      ()     => apiFetch("/api/matter/status"),
    qrcode:      ()     => apiFetch("/api/matter/qrcode"),
    start:       ()     => apiFetch("/api/matter/bridge/start",  { method: "POST" }),
    stop:        ()     => apiFetch("/api/matter/bridge/stop",   { method: "POST" }),
    sync:        ()     => apiFetch("/api/matter/sync",          { method: "POST" }),
  },
};
