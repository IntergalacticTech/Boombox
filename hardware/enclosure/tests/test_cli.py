import json
import subprocess
import sys
from pathlib import Path


def run(*args):
    return subprocess.run([sys.executable, "-m", "boombox_enclosure", *args], capture_output=True, text=True)


def test_generates_everything(tmp_path):
    r = run("designs/mk1.json", "--out", str(tmp_path))
    assert r.returncode == 0, r.stderr
    names = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()}
    assert names >= {"model-classic.glb", "model-wood.glb", "model.dae", "model.stl", "viewer.html",
                     "cut-sheet.html", "bom.md", "cnc/sheet-12mm-1-front.dxf", "cnc/sheet-18mm-1-back.dxf"}
    viewer = (tmp_path / "viewer.html").read_text()
    assert 'data-finish="classic"' in viewer and 'data-finish="wood"' in viewer


def test_all_optional_parts_off_still_generates(tmp_path):  # Review Focus 3
    d = json.loads(Path("designs/mk1.json").read_text())
    for k in ("rfid", "led_bar", "source_row", "encoder", "handle"):
        d["parts"][k]["enabled"] = False
    f = tmp_path / "bare.json"
    f.write_text(json.dumps(d))
    r = run(str(f), "--out", str(tmp_path / "o"))
    assert r.returncode == 0, r.stderr


def test_design_error_is_one_line(tmp_path):
    d = json.loads(Path("designs/mk1.json").read_text())
    d["parts"]["screen"]["window"] = [185, 101]
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(d))
    r = run(str(f), "--out", str(tmp_path / "o"))
    assert r.returncode == 2 and "Traceback" not in r.stderr and "window" in r.stderr


def test_missing_design_file_is_one_line(tmp_path):
    r = run(str(tmp_path / "nope.json"))
    assert r.returncode == 2 and "Traceback" not in r.stderr
