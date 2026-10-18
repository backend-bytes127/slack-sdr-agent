"""Generate docs/diagrams/architecture.excalidraw (open it at excalidraw.com to edit).

  python3 docs/diagrams/build_architecture.py
"""
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent / "architecture.excalidraw"
random.seed(7)
ELEMENTS = []

INK = "#1e1e1e"
COLORS = {
    "slack": "#ffd8a8", "edge": "#e9ecef", "n8n": "#ffc9c9", "db": "#b2f2bb",
    "data": "#a5d8ff", "ai": "#d0bfff", "tools": "#fcc2d7", "note": "#fff3bf",
}


def _base(kind, x, y, w, h, **extra):
    el = {
        "id": f"{kind}-{len(ELEMENTS)}", "type": kind, "x": x, "y": y, "width": w, "height": h, "angle": 0,
        "strokeColor": INK, "backgroundColor": "transparent", "fillStyle": "solid", "strokeWidth": 2,
        "strokeStyle": "solid", "roughness": 1, "opacity": 100, "groupIds": [], "frameId": None,
        "roundness": None, "seed": random.randint(1, 2**31), "version": 1, "versionNonce": random.randint(1, 2**31),
        "isDeleted": False, "boundElements": None, "updated": 1, "link": None, "locked": False,
    }
    el.update(extra)
    ELEMENTS.append(el)
    return el


def text(x, y, content, size=20, color=INK, align="center", width=None):
    lines = content.split("\n")
    w = width or max(len(line) for line in lines) * size * 0.55
    h = len(lines) * size * 1.25
    left = x - w / 2 if align == "center" else x
    return _base("text", left, y, w, h, text=content, originalText=content, fontSize=size, fontFamily=1,
                 textAlign=align, verticalAlign="top", baseline=round((len(lines) - 1) * size * 1.25 + size * 0.9), containerId=None, lineHeight=1.25,
                 strokeColor=color, autoResize=True)


def box(x, y, w, h, fill, title, body="", title_size=24, body_size=16, shape="rectangle", dashed=False):
    _base(shape, x, y, w, h, backgroundColor=fill, roundness={"type": 3} if shape == "rectangle" else None,
          strokeStyle="dashed" if dashed else "solid")
    total = title_size * 1.25 + (len(body.split("\n")) * body_size * 1.25 + 6 if body else 0)
    top = y + (h - total) / 2
    text(x + w / 2, top, title, title_size)
    if body:
        text(x + w / 2, top + title_size * 1.25 + 6, body, body_size, color="#343a40")


def arrow(x1, y1, x2, y2, label=None, both=False, dashed=False):
    _base("arrow", x1, y1, x2 - x1, y2 - y1, points=[[0, 0], [x2 - x1, y2 - y1]], lastCommittedPoint=None,
          startBinding=None, endBinding=None, startArrowhead="arrow" if both else None, endArrowhead="arrow",
          roundness={"type": 2}, strokeStyle="dashed" if dashed else "solid", elbowed=False)
    if label:
        text((x1 + x2) / 2, (y1 + y2) / 2 - 26, label, 14, color="#495057")


# Title
text(820, 20, "Slack SDR Agent — architecture", 36)
text(820, 70, "/prospect <LinkedIn URL>  →  researched lead + CRM + follow-up, in ~20 s", 18, color="#495057")

# Left: SDR + Slack
box(40, 300, 220, 170, COLORS["slack"], "Slack", "/prospect\nlead card + buttons\nmodals · threads")
text(150, 200, "SDR", 22)
_base("ellipse", 128, 140, 44, 44, backgroundColor=COLORS["note"])
arrow(150, 232, 150, 296, both=True)

# Edge: ngrok + nginx
box(330, 300, 180, 80, COLORS["edge"], "ngrok", "public HTTPS", 20, 14)
box(330, 410, 180, 80, COLORS["edge"], "nginx :8088", "webhooks only\neditor = localhost", 20, 14)
arrow(262, 350, 326, 340, "signed")
arrow(420, 382, 420, 406)

# Centre: n8n
_base("rectangle", 590, 130, 460, 560, backgroundColor=COLORS["n8n"], roundness={"type": 3}, fillStyle="hachure")
text(820, 145, "n8n (Docker) — 15 workflows", 24)
rows = [
    ("WF1 Intake", "verify signature · ack < 3 s · dedupe"),
    ("Enrich (sub)", "profile → email waterfall → LLM research"),
    ("WF2 Enriched", "HubSpot upsert · research note · lead card"),
    ("WF3 Actions", "No answer · Picked up · Wrong person"),
    ("Expansion (sub)", "people search → LLM fit → top 8"),
    ("WF5 Expansion", "suggestions card · Add / Skip"),
    ("WF4 Ops", "errors · sweeps · 18:00 summary"),
]
for i, (name, desc) in enumerate(rows):
    y = 195 + i * 68
    _base("rectangle", 615, y, 410, 56, backgroundColor="#ffffff", roundness={"type": 3})
    text(630, y + 6, name, 18, align="left", width=180)
    text(630, y + 30, desc, 14, color="#495057", align="left", width=380)
arrow(512, 450, 586, 450, "/webhook/*")

# Bottom: Supabase
box(640, 760, 360, 120, COLORS["db"], "Supabase Postgres", "source of truth · atomic status claims\nidempotent enrolments · RLS · views")
arrow(820, 692, 820, 756, both=True)

# Right: data providers
box(1150, 120, 300, 110, COLORS["data"], "Deepline", "LinkedIn profile · company page\nemployees · Datagma · Hunter", 22)
box(1150, 250, 300, 90, COLORS["data"], "Prospeo", "person enrich · people search", 22)
box(1150, 360, 300, 90, COLORS["ai"], "LLM (gpt-5-mini)", "research · persona fit · drafts", 22)
for y in (175, 295, 405):
    arrow(1052, 300 if y != 405 else 420, 1146, y)
text(1300, 90, "enrich & reason", 16, color="#495057")

# Right: systems of record
box(1150, 490, 300, 80, COLORS["tools"], "HubSpot", "company · contact · notes · calls", 22, 14)
box(1150, 590, 300, 80, COLORS["tools"], "HeyReach", "LinkedIn sequences", 22, 14)
box(1150, 690, 300, 80, COLORS["tools"], "Instantly", "email sequences", 22, 14)
for y in (530, 630, 730):
    arrow(1052, 600, 1146, y)
text(1300, 790, "act", 16, color="#495057")

# Callouts
box(40, 560, 470, 200, COLORS["note"], "Why it's safe", "• HMAC-verified Slack requests\n• one atomic UPDATE per button\n"
    "  → double-clicks & retries are no-ops\n• unique index: enrol once per lead\n• every error → Slack thread + Retry", 20, 15)

OUT.write_text(json.dumps({"type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
                           "elements": ELEMENTS, "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
                           "files": {}}, indent=1))
print(f"wrote {OUT} ({len(ELEMENTS)} elements)")
