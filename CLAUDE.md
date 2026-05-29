# ESPAI — Codebase conventions

## Tooltip rule (mandatory for all UI work)

Every interactive or informational element in the frontend **must** carry a `data-tip="…"` attribute with a one-sentence description. This is enforced globally by the `#appTip` system wired in `app.js`.

### Static HTML elements (`index.html`)
Add the attribute directly:
```html
<button id="btnScan" class="btn btn-secondary btn-sm" data-tip="Probe the local subnet for ESPAI nodes">Scan LAN</button>
```

### Dynamically generated elements (`app.js` template literals)
Embed `data-tip` inline in the HTML string:
```js
card.innerHTML = `
  <span class="device-dot online" data-tip="Online — seen within 2 minutes"></span>
`;
```

### Dynamically generated elements (created with `el()`)
Set via `dataset.tip` after creation:
```js
const btn = el("button", "btn btn-secondary btn-sm", "Pair");
btn.dataset.tip = "Pair this device with the hub to enable OTA and trusted commands";
```

### What NOT to use
- `title="…"` — native browser tooltip; inconsistent style, doesn't work on mobile. Replace any existing `title=` with `data-tip=`.
- Omitting tooltips entirely — every button, badge, status dot, and tag must have one.

### Complex structured tooltips
For rows that need a badge + name + description (e.g., Doctor dialog), use the separate `_showDoctorTooltip` / `_hideDoctorTooltip` system. Don't use `#appTip` for those.

### The `#appTip` system at a glance
- Single `mouseover` listener at document level catches all `[data-tip]` elements, including dynamically added ones.
- 400 ms delay before showing; hides on `mouseout`, scroll, or click.
- Centered below the element; flips upward if near the bottom edge; clamped left/right within the viewport.
- Implemented in `hub/frontend/static/js/app.js` (search `_appTip`).
- Styled in `hub/frontend/static/css/app.css` (`.app-tip`).

---

## Security constraints (non-negotiable)

- Never expose secrets in Git.
- Never hardcode: Wi-Fi credentials, API keys, MAC addresses, GPS locations, personal infrastructure names, local network topology.
- OTA: requires pairing + compatibility check + checksum validation + audit log.
- Recipes: must support sanitization; keep public and private knowledge separate.
- Workers: arbitrary code execution — require explicit permissions and sandboxing; imported workers default to quarantined.
- Agent Bench: dev lane only in MVP; agents may NOT deploy to production/stable devices; may NOT access `secrets/` or `*.private.yaml`; may NOT modify `data/`, `backups/`, private overlays, or production configs; may NOT promote releases (humans only); all agent actions are logged.
