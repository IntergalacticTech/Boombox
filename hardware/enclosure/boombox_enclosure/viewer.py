"""A one-file 3D viewer page for the generated GLB models (rotate, zoom, switch finish)."""
from html import escape

from .derive import Cabinet
from .finishes import FINISHES

MODEL_VIEWER = "https://cdn.jsdelivr.net/npm/@google/model-viewer@4.0.0/dist/model-viewer.min.js"


def render_viewer(cab: Cabinet, finishes: list) -> str:
    buttons = "".join(f'<button data-finish="{k}">{escape(FINISHES[k].label)}</button>' for k in finishes)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(cab.name)} · 3D</title>
<script type="module" src="{MODEL_VIEWER}"></script>
<style>
html,body{{margin:0;height:100%;background:#e9e7e2;font:15px -apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}
model-viewer{{width:100%;height:100%;background:radial-gradient(circle at 50% 35%,#f7f6f3,#d6d3cc)}}
nav{{position:fixed;left:16px;top:16px;display:flex;gap:8px;align-items:center}}
nav b{{margin-right:8px}}
button{{font:inherit;padding:8px 14px;border:1px solid #1b1b1b;border-radius:6px;background:#fff;cursor:pointer}}
button[aria-pressed=true]{{background:#1b1b1b;color:#fff}}
.bare nav{{display:none}}
</style></head><body>
<nav><b>{escape(cab.name)}</b>{buttons}</nav>
<model-viewer id="mv" camera-controls shadow-intensity="1" shadow-softness="0.9" exposure="1.05"
  environment-image="neutral" tone-mapping="neutral" camera-orbit="-30deg 75deg 78%" field-of-view="26deg"
  interaction-prompt="none" alt="{escape(cab.name)} enclosure"></model-viewer>
<script>
const q = new URLSearchParams(location.search), mv = document.getElementById("mv");
const show = k => {{
  mv.src = "model-" + k + ".glb";
  document.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b.dataset.finish === k));
}};
document.querySelectorAll("button").forEach(b => b.onclick = () => show(b.dataset.finish));
if (q.get("orbit")) mv.cameraOrbit = q.get("orbit");
if (q.has("bare")) document.body.classList.add("bare");
mv.addEventListener("load", () => document.title = "ready");
show(q.get("finish") || "{finishes[0]}");
</script></body></html>
"""
