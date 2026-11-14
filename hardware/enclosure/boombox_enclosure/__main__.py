"""python -m boombox_enclosure designs/mk1.json  ->  out/mk1/ (model, cut sheet, BOM, CNC files)."""
import argparse
import functools
import http.server
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .bom import render_bom
from .cutsheet import render_cut_sheet
from .derive import derive
from .design import DesignError, load_design
from .dxf import write_dxfs
from .finishes import FINISHES
from .model import export_model
from .nest import cnc_nest, saw_nest
from .viewer import render_viewer

VIEWS = {"front": "-30deg 75deg 78%", "back": "150deg 75deg 78%"}


def render_pngs(out: Path, finishes: list) -> None:
    """Screenshot the viewer page for each finish and view. Needs the agent-browser CLI and network (CDN)."""
    ab = shutil.which("agent-browser")
    if not ab:
        print("renders skipped: agent-browser not found")
        return
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    handler = functools.partial(Quiet, directory=str(out))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def call(*args):
        return subprocess.run([ab, *args], capture_output=True, text=True, timeout=90, env=env).stdout

    # headless Chrome has no GPU; software WebGL is enough for a still
    gl = "--use-angle=swiftshader,--enable-unsafe-swiftshader,--ignore-gpu-blocklist"
    env = {**os.environ, "AGENT_BROWSER_ARGS": gl}
    try:
        call("close")  # launch args only apply to a fresh browser
        call("set", "viewport", "1600", "1000")
        for key in finishes:
            for view, orbit in VIEWS.items():
                url = f"http://127.0.0.1:{server.server_port}/viewer.html?bare&finish={key}&orbit={orbit}"
                call("open", url.replace(" ", "%20"))
                for _ in range(40):
                    if "ready" in call("eval", "document.title"):
                        break
                    time.sleep(0.5)
                else:
                    print(f"renders skipped: the 3D viewer did not load ({key} {view})")
                    return
                time.sleep(1.5)  # let the first frames and the shadow settle
                call("screenshot", str(out / f"render-{key}-{view}.png"))
    finally:
        server.shutdown()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="boombox_enclosure", description=__doc__)
    ap.add_argument("design", help="design file, e.g. designs/mk1.json")
    ap.add_argument("--out", help="output folder (default: out/<design name>/)")
    ap.add_argument("--render", action="store_true", help="also write PNG renders (needs agent-browser)")
    args = ap.parse_args(argv)
    try:
        design = load_design(args.design)
        cab = derive(design)
        finishes = design["cabinet"]["finishes"]
        unknown = [f for f in finishes if f not in FINISHES]
        if unknown:
            raise DesignError(f"unknown finish {unknown[0]!r}; use one of {', '.join(FINISHES)}")
        saw, cnc = saw_nest(cab), cnc_nest(cab)
    except (DesignError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / "out" / Path(args.design).stem
    out.mkdir(parents=True, exist_ok=True)
    for key in finishes:
        export_model(cab, FINISHES[key], out)
    (out / "viewer.html").write_text(render_viewer(cab, finishes))
    (out / "cut-sheet.html").write_text(render_cut_sheet(cab, saw))
    (out / "bom.md").write_text(render_bom(cab, saw))
    write_dxfs(cnc, out / "cnc", margin=design["cabinet"]["sheet_margin"])
    if args.render:
        render_pngs(out, finishes)
    W, H, D = cab.outer
    print(f"{cab.name}: {W:g} x {H:g} x {D:g} mm, {cab.chamber_volume_l:.2f} L per chamber -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
