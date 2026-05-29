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
    checkin:        (body)      => apiFetch("/api/devices/checkin",      { method: "POST", body: JSON.stringify(body) }),
    addManual:      (body)      => apiFetch("/api/devices/manual",       { method: "POST", body: JSON.stringify(body) }),
    initiatePair:   (id)        => apiFetch(`/api/devices/pair/initiate/${id}`, { method: "POST" }),
    confirmPair:    (body)      => apiFetch("/api/devices/pair/confirm", { method: "POST", body: JSON.stringify(body) }),
    delete:         (id)        => apiFetch(`/api/devices/${id}`,        { method: "DELETE" }),
    scan:           (subnet)    => apiFetch(
      "/api/devices/scan" + (subnet ? `?subnet=${encodeURIComponent(subnet)}` : ""),
      { method: "POST" }
    ),
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
    approvalMode:      (id)      => apiFetch(`/api/projects/${id}/approval-mode`),
    setApprovalMode:   (id, mode)=> apiFetch(`/api/projects/${id}/approval-mode?mode=${encodeURIComponent(mode)}`, { method: "PUT" }),
    // Project data store
    dataLatest:  (id)             => apiFetch(`/api/projects/${id}/data/latest`),
    dataHistory: (id, params)     => {
      const q = new URLSearchParams(Object.fromEntries(Object.entries(params || {}).filter(([,v]) => v != null))).toString();
      return apiFetch(`/api/projects/${id}/data${q ? "?" + q : ""}`);
    },
    dataPush:    (id, body)       => apiFetch(`/api/projects/${id}/data`, { method: "POST", body: JSON.stringify(body) }),
    dataClear:   (id)             => apiFetch(`/api/projects/${id}/data`, { method: "DELETE" }),
  },

  // Registry
  workers:  {
    list:          ()         => apiFetch("/api/workers/"),
    get:           (n)        => apiFetch(`/api/workers/${n}`),
    test:          (n, body)  => apiFetch(`/api/workers/${encodeURIComponent(n)}/test`, { method: "POST", body: JSON.stringify(body) }),
    compat:        (n)        => apiFetch(`/api/workers/${encodeURIComponent(n)}/compat`),
    setQuarantine: (n, state) => apiFetch(`/api/workers/${encodeURIComponent(n)}/quarantine?quarantine=${state}`, { method: "PATCH" }),
  },
  recipes: {
    list:     ()  => apiFetch("/api/recipes/"),
    get:      (n) => apiFetch(`/api/recipes/${n}`),
    validate: (n) => apiFetch(`/api/recipes/${encodeURIComponent(n)}/validate`),
    export:   (n) => apiFetch(`/api/recipes/${encodeURIComponent(n)}/export`),
    compat:   (n) => apiFetch(`/api/recipes/${encodeURIComponent(n)}/compat`),
  },
  cards:    { list: () => apiFetch("/api/cards/"),    get: (n) => apiFetch(`/api/cards/${n}`) },

  // Design
  design: {
    tokens: ()       => apiFetch("/api/design/tokens"),
    themes: ()       => apiFetch("/api/design/themes"),
    skins:  ()       => apiFetch("/api/design/skins"),
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
    list:   ()           => apiFetch("/api/rules/"),
    get:    (id)         => apiFetch(`/api/rules/${id}`),
    create: (body)       => apiFetch("/api/rules/",   { method: "POST",   body: JSON.stringify(body) }),
    update: (id, body)   => apiFetch(`/api/rules/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete: (id)         => apiFetch(`/api/rules/${id}`, { method: "DELETE" }),
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
    install:       (tool)       => apiFetch(`/api/agent-bench/install/${encodeURIComponent(tool)}`, { method: "POST" }),
  },
};
