"""CRUD over rfid_bindings."""
from __future__ import annotations

from pathlib import Path

from boombox_rfid.db import connect, migrate
from boombox_rfid.bindings import bind, get_binding, list_bindings, record_tap, unbind
from boombox_rfid.models import BindingKind


def _setup(tmp_path: Path):
    conn = connect(tmp_path / "lib.db")
    migrate(conn)
    return conn


def test_bind_then_get(tmp_path: Path):
    conn = _setup(tmp_path)
    bind(conn, "0001", BindingKind.ALBUM, "al1", label="Arrival")
    b = get_binding(conn, "0001")
    assert b is not None
    assert b.kind == BindingKind.ALBUM
    assert b.target_id == "al1"
    assert b.label == "Arrival"
    assert b.tap_count == 0


def test_bind_replaces_on_uid_conflict(tmp_path: Path):
    conn = _setup(tmp_path)
    bind(conn, "0001", BindingKind.ALBUM, "al1")
    bind(conn, "0001", BindingKind.PLAYLIST, "pl5", label="Mix")
    b = get_binding(conn, "0001")
    assert b is not None
    assert b.kind == BindingKind.PLAYLIST
    assert b.target_id == "pl5"
    # tap_count preserved across rebind (UPSERT updates fields, not counter)
    assert b.tap_count == 0


def test_unbind_returns_true_when_removed(tmp_path: Path):
    conn = _setup(tmp_path)
    bind(conn, "0001", BindingKind.ALBUM, "al1")
    assert unbind(conn, "0001") is True
    assert get_binding(conn, "0001") is None


def test_unbind_returns_false_when_not_found(tmp_path: Path):
    conn = _setup(tmp_path)
    assert unbind(conn, "nope") is False


def test_record_tap_bumps_counter(tmp_path: Path):
    conn = _setup(tmp_path)
    bind(conn, "0001", BindingKind.ALBUM, "al1")
    record_tap(conn, "0001")
    record_tap(conn, "0001")
    b = get_binding(conn, "0001")
    assert b is not None
    assert b.tap_count == 2
    assert b.last_tap_ts is not None and b.last_tap_ts > 0


def test_list_bindings_orders_by_added_desc(tmp_path: Path):
    conn = _setup(tmp_path)
    bind(conn, "0001", BindingKind.ALBUM, "al1")
    import time; time.sleep(0.01)
    bind(conn, "0002", BindingKind.ALBUM, "al2")
    rows = list_bindings(conn)
    assert [r.uid for r in rows] == ["0002", "0001"]
