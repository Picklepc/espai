from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..config import CARDS_DIR
from ..registry.loader import scan_folder
from ..reg_files import (FileWrite, NewItemRequest,
                          delete_item, list_files, read_file,
                          scaffold_card, write_file,
                          create_file, delete_file)

router = APIRouter()


@router.post("/new")
def create_card(body: NewItemRequest):
    return scaffold_card(CARDS_DIR, body)


@router.get("/")
def list_cards():
    return scan_folder(CARDS_DIR, "card")


@router.get("/{card_name}")
def get_card(card_name: str):
    all_cards = scan_folder(CARDS_DIR, "card")
    for c in all_cards:
        if c.get("name") == card_name or c.get("_folder") == card_name:
            return c
    raise HTTPException(404, f"Card {card_name!r} not found")


@router.get("/{card_name}/preview", response_class=HTMLResponse)
def preview_card(card_name: str):
    """
    Serve the card's preview.html if present, otherwise generate a metadata
    preview from the card YAML showing its config schema with dummy values.
    """
    all_cards = scan_folder(CARDS_DIR, "card")
    card = next((c for c in all_cards
                 if c.get("name") == card_name or c.get("_folder") == card_name), None)
    if not card:
        raise HTTPException(404, f"Card {card_name!r} not found")

    # Check for a hand-authored preview.html in the card folder
    folder = CARDS_DIR / card.get("_folder", card_name)
    preview_file = folder / "preview.html"
    if preview_file.exists():
        return HTMLResponse(content=preview_file.read_text(encoding="utf-8"))

    # Generate a fallback metadata preview
    return HTMLResponse(content=_generate_preview(card))


def _generate_preview(card: dict) -> str:
    """Generate a self-contained HTML preview from card YAML metadata."""
    import json as _json
    name     = card.get("display_name") or card.get("name", "Card")
    desc     = card.get("description", "").strip()
    cat      = card.get("category", "")
    source   = (card.get("event_source") or {}).get("type", "unknown")
    config   = card.get("config", {})
    fields   = config.get("fields", [])
    boards   = ", ".join(card.get("compatible_boards") or []) or "all boards"

    # Build field rows with demo values
    import random, math
    _rng = random.Random(42)
    field_rows = ""
    for f in fields:
        key   = f.get("key", "")
        label = f.get("label", key)
        unit  = f.get("unit", "")
        val   = round(_rng.uniform(18, 75), 1)
        thresh = (config.get("alert_thresholds") or {}).get(key, {})
        alert = thresh and not (thresh.get("min", -999) <= val <= thresh.get("max", 9999))
        color = "#e03248" if alert else "#20bf96"
        # Sparkline as a tiny SVG polyline
        pts = [round(_rng.uniform(15, 80), 1) for _ in range(20)]
        mn, mx = min(pts), max(pts)
        span = mx - mn or 1
        coords = " ".join(f"{i*8},{40-((v-mn)/span)*30}" for i, v in enumerate(pts))
        spark = f'<svg viewBox="0 0 152 42" style="width:100%;height:42px"><polyline points="{coords}" fill="none" stroke="{color}" stroke-width="1.5" opacity=".8"/></svg>'
        field_rows += f"""
        <div class="field-row">
          <div class="field-meta">
            <span class="field-label">{label}</span>
            <span class="field-val" style="color:{color}">{val}<span class="field-unit"> {unit}</span></span>
          </div>
          {spark if f.get("sparkline") else ""}
        </div>"""

    config_json = _json.dumps(config, indent=2) if config else "{}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — Preview</title>
<style>
  :root{{
    --bg:#080c10;--surface:#0d1824;--card:#121f30;--border:#1c3650;
    --text:#eeddc4;--muted:#7a9aaa;--accent:#1aafc4;--accent2:#e07828;
    --success:#20bf96;--warning:#f0a820;--danger:#e03248;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;padding:16px;min-height:100vh}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;max-width:360px;margin:0 auto}}
  .card-header{{padding:12px 16px 10px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}}
  .card-title{{font-weight:700;font-size:14px}}
  .card-cat{{font-family:monospace;font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}}
  .card-body{{padding:14px 16px}}
  .field-row{{margin-bottom:12px}}
  .field-meta{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px}}
  .field-label{{font-size:11px;color:var(--muted)}}
  .field-val{{font-size:1.6rem;font-weight:900;font-family:monospace;line-height:1}}
  .field-unit{{font-size:12px;font-weight:400;opacity:.7}}
  .card-footer{{padding:8px 16px 12px;border-top:1px solid var(--border);font-family:monospace;font-size:9px;color:var(--muted);display:flex;gap:12px;flex-wrap:wrap}}
  .badge{{background:rgba(26,175,196,.12);color:var(--accent);border-radius:3px;padding:2px 7px;letter-spacing:.06em}}
  .desc{{font-size:12px;color:var(--muted);line-height:1.55;padding:12px 16px;border-bottom:1px solid var(--border)}}
  details{{margin-top:12px}}
  summary{{font-size:11px;color:var(--accent);cursor:pointer;font-family:monospace;letter-spacing:.06em;text-transform:uppercase}}
  pre{{font-size:10px;overflow:auto;max-height:160px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px;margin-top:8px;color:var(--muted)}}
  .preview-banner{{font-family:monospace;font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--warning);text-align:center;padding:6px;background:rgba(240,168,32,.08);margin-bottom:14px;border-radius:6px}}
</style>
</head>
<body>
<div class="preview-banner">◈ preview — dummy data ◈</div>
<div class="card">
  <div class="card-header">
    <span class="card-title">{name}</span>
    <span class="card-cat">{cat}</span>
  </div>
  {f'<div class="desc">{desc}</div>' if desc else ""}
  <div class="card-body">
    {field_rows if field_rows else '<div style="color:var(--muted);font-size:12px;text-align:center;padding:20px 0">No field config defined</div>'}
  </div>
  <div class="card-footer">
    <span>source: <span class="badge">{source}</span></span>
    <span>boards: {boards}</span>
  </div>
</div>
{f'<details style="max-width:360px;margin:14px auto 0"><summary>Config YAML</summary><pre>{config_json}</pre></details>' if config else ""}
</body>
</html>"""


# ── Card item management ──────────────────────────────────────────────────────

def _card_folder(card_name: str) -> str:
    all_cards = scan_folder(CARDS_DIR, "card")
    c = next((c for c in all_cards
               if c.get("name") == card_name or c.get("_folder") == card_name), None)
    if not c:
        raise HTTPException(404, f"Card {card_name!r} not found")
    return c["_folder"]


@router.delete("/{card_name}")
def delete_card(card_name: str):
    return delete_item(CARDS_DIR, _card_folder(card_name))


@router.get("/{card_name}/files")
def list_card_files(card_name: str):
    return list_files(CARDS_DIR, _card_folder(card_name))


@router.get("/{card_name}/files/{file_path:path}")
def read_card_file(card_name: str, file_path: str):
    return read_file(CARDS_DIR, _card_folder(card_name), file_path)


@router.put("/{card_name}/files/{file_path:path}")
def write_card_file(card_name: str, file_path: str, body: FileWrite):
    return write_file(CARDS_DIR, _card_folder(card_name), file_path, body)


@router.post("/{card_name}/files/{file_path:path}")
def create_card_file(card_name: str, file_path: str, body: FileWrite):
    return create_file(CARDS_DIR, _card_folder(card_name), file_path, body)


@router.delete("/{card_name}/files/{file_path:path}")
def delete_card_file(card_name: str, file_path: str):
    return delete_file(CARDS_DIR, _card_folder(card_name), file_path)
