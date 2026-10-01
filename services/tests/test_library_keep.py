"""keep.py — keep/unkeep with pin fall-back, keep state, offline facts."""
from __future__ import annotations

from pathlib import Path

from boombox_library import keep as k
from boombox_library.cache_drive import CacheDriveState
from boombox_library.db import connect, migrate
from boombox_library.models import PinKind
from boombox_library.pins import all_pinned_track_ids, reconcile_starred


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.cancelled: list[str] = []
        self.snap = {"queued": 0, "in_flight": [], "paused": None}

    def enqueue(self, tid):
        if tid in self.enqueued:
            return False
        self.enqueued.append(tid)
        return True

    def cancel(self, ids):
        hit = [i for i in ids if i in self.enqueued and i not in self.cancelled]
        self.cancelled += hit
        return len(hit)

    def snapshot(self):
        return dict(self.snap)


def _db(tmp_path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) VALUES('ar1','Joni','joni',2,0)")
    for al, name, starred in (("al1", "Blue", 0), ("al2", "Court and Spark", 1)):
        conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,duration_s,is_compilation,"
                     "navidrome_starred,updated_at) VALUES(?,?,?,'ar1',2,60,0,?,0)", (al, name, name.lower(), starred))
    for tid, al in (("t1", "al1"), ("t2", "al1"), ("t3", "al1"), ("t4", "al2"), ("t5", "al2")):
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,size_bytes,content_type,"
                     "navidrome_starred,updated_at) VALUES(?,?,?,30,'mp3',1000,'audio/mpeg',0,0)",
                     (tid, al, tid.upper()))
    conn.execute("INSERT INTO playlists(id,name,song_count,owner,public,updated_at) VALUES('pl1','Mix',1,'u',0,0)")
    conn.execute("INSERT INTO playlist_tracks(playlist_id,track_id,position) VALUES('pl1','t2',0)")
    return conn


def _present(conn, tid, path="/m/x.mp3", size=1000):
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,downloaded_at) "
                 "VALUES(?,'present',?,?,0) ON CONFLICT(track_id) DO UPDATE SET status='present', "
                 "local_path=excluded.local_path, size_bytes=excluded.size_bytes", (tid, path, size))


def _source(conn, kind, tid):
    row = conn.execute("SELECT source FROM pins WHERE target_kind=? AND target_id=?", (kind, tid)).fetchone()
    return None if row is None else row["source"]


def test_keep_pins_user_and_enqueues_its_tracks(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    _present(conn, "t1")
    r = k.keep(conn, q, PinKind.ALBUM, "al1")
    assert r == {"ok": True, "queued": 3,
                 "keep": {"state": "kept", "tracks_total": 3, "tracks_present": 1}}
    assert q.enqueued == ["t1", "t2", "t3"] and _source(conn, "album", "al1") == "user"


def test_keep_is_idempotent_and_works_without_a_queue(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    k.keep(conn, q, PinKind.ALBUM, "al1")
    assert k.keep(conn, q, PinKind.ALBUM, "al1")["queued"] == 0
    assert k.keep(conn, None, PinKind.PLAYLIST, "pl1")["keep"]["state"] == "kept"


def test_unkeep_cancels_only_orphaned_queued_tracks(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    k.keep(conn, q, PinKind.ALBUM, "al1")
    k.keep(conn, q, PinKind.PLAYLIST, "pl1")
    r = k.unkeep(conn, q, PinKind.ALBUM, "al1", starred_auto_pin=True)
    assert q.cancelled == ["t1", "t3"]          # t2 is still in the kept playlist
    assert r["cancelled"] == 2 and r["keep"]["state"] == "none"
    assert _source(conn, "album", "al1") is None
    assert k.unkeep(conn, q, PinKind.ALBUM, "al1", starred_auto_pin=True)["ok"] is True


def test_unkeep_starred_album_falls_back_to_starred_pin(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    reconcile_starred(conn)
    assert _source(conn, "album", "al2") == "starred"
    k.keep(conn, q, PinKind.ALBUM, "al2")
    assert _source(conn, "album", "al2") == "user"      # one row per target: replaced
    r = k.unkeep(conn, q, PinKind.ALBUM, "al2", starred_auto_pin=True)
    assert _source(conn, "album", "al2") == "starred"
    assert {"t4", "t5"} <= all_pinned_track_ids(conn)
    assert r["cancelled"] == 0 and r["keep"]["state"] == "starred"


def test_unkeep_with_starred_auto_pin_off_drops_the_pin(tmp_path):
    conn = _db(tmp_path)
    k.keep(conn, None, PinKind.ALBUM, "al2")
    k.unkeep(conn, None, PinKind.ALBUM, "al2", starred_auto_pin=False)
    assert _source(conn, "album", "al2") is None


def test_unkeep_card_bound_album_falls_back_to_rfid_pin(tmp_path):
    from boombox_rfid.bindings import bind
    from boombox_rfid.db import migrate as rfid_migrate
    from boombox_rfid.models import BindingKind
    conn = _db(tmp_path)
    rfid_migrate(conn)
    bind(conn, "04aa", BindingKind.ALBUM, "al1", "Blue")
    assert _source(conn, "album", "al1") == "rfid"
    k.keep(conn, None, PinKind.ALBUM, "al1")
    k.unkeep(conn, None, PinKind.ALBUM, "al1", starred_auto_pin=True)
    assert _source(conn, "album", "al1") == "rfid"
    assert k.keep_state(conn, PinKind.ALBUM, "al1")["state"] == "none"


def test_keep_state_for_artist_and_playlist(tmp_path):
    conn = _db(tmp_path)
    _present(conn, "t2")
    _present(conn, "t4")
    assert k.keep_state(conn, PinKind.ARTIST, "ar1") == {"state": "none", "tracks_total": 5, "tracks_present": 2}
    assert k.keep_state(conn, PinKind.PLAYLIST, "pl1") == {"state": "none", "tracks_total": 1, "tracks_present": 1}


def test_offline_ids_and_flags(tmp_path):
    conn = _db(tmp_path)
    _present(conn, "t2")
    assert k.offline_ids(conn) == {"album_ids": ["al1"], "artist_ids": ["ar1"], "playlist_ids": ["pl1"]}
    flags = k.offline_flags(conn, [
        {"content_type": "track", "id": "t2", "title": "T2"},
        {"content_type": "track", "id": "t4", "title": "T4"},
        {"content_type": "album", "id": "al1", "title": "Blue"},
        {"content_type": "album", "id": "al2", "title": "Court and Spark"},
        {"content_type": "artist", "id": "ar1", "title": "Joni"},
    ])
    assert [f["offline"] for f in flags] == [True, False, True, False, True]
    assert flags[0]["title"] == "T2"


def test_storage_overview_reports_downloads_and_no_space(tmp_path):
    conn = _db(tmp_path)
    reconcile_starred(conn)
    k.keep(conn, None, PinKind.ALBUM, "al1")
    _present(conn, "t1", size=1500)
    conn.execute("INSERT INTO cache_state(track_id,status,error_message) VALUES('t2','error','boom')")
    conn.execute("INSERT INTO cache_state(track_id,status,error_message) VALUES('t3','no_space','no space')")
    q = FakeQueue()
    q.snap = {"queued": 4, "in_flight": ["t4"], "paused": "low_space"}
    drive = CacheDriveState(present=True, mount_path=Path("/opt/boombox/storage/music"),
                            free_bytes=10, total_bytes=100, internal=True)
    o = k.storage_overview(conn, drive, 20, q)
    assert o["drive"] == {"present": True, "internal": True, "mount_path": "/opt/boombox/storage/music",
                          "total_bytes": 100, "free_bytes": 10, "reserve_bytes": 20,
                          "music_bytes": 1500, "kept_tracks": 1}
    assert o["downloads"] == {"active": True, "queued": 4, "in_flight": [{"id": "t4", "title": "T4"}],
                              "paused": "low_space", "failed": 1, "no_space": 1}
    assert sorted(o["kept"], key=lambda i: i["id"]) == [
        {"kind": "album", "id": "al1", "name": "Blue", "source": "user",
         "tracks_total": 3, "tracks_present": 1, "bytes": 1500},
        {"kind": "album", "id": "al2", "name": "Court and Spark", "source": "starred",
         "tracks_total": 2, "tracks_present": 0, "bytes": 0},
    ]


def test_storage_overview_without_drive_or_queue(tmp_path):
    conn = _db(tmp_path)
    conn.execute("UPDATE tracks SET navidrome_starred=1 WHERE id='t5'")
    reconcile_starred(conn)
    o = k.storage_overview(conn, None, 20, None)
    assert o["drive"]["present"] is False and o["drive"]["free_bytes"] is None
    assert o["downloads"]["active"] is False and o["downloads"]["paused"] is None
    assert o["kept"][-1] == {"kind": "starred_tracks", "id": "", "name": "Starred songs", "source": "starred",
                             "tracks_total": 1, "tracks_present": 0, "bytes": 0}


def test_remove_kept_deletes_orphaned_files_now(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    f1, f2 = tmp_path / "t1.mp3", tmp_path / "t2.mp3"
    f1.write_bytes(b"x" * 10)
    f2.write_bytes(b"y")
    k.keep(conn, q, PinKind.ALBUM, "al1")
    k.keep(conn, q, PinKind.PLAYLIST, "pl1")
    _present(conn, "t1", str(f1), 10)
    _present(conn, "t2", str(f2), 1)
    status, r = k.remove_kept(conn, q, PinKind.ALBUM, "al1", starred_auto_pin=True, cache_root=tmp_path)
    assert status == 200 and r["removed_tracks"] == 1 and r["freed_bytes"] == 10
    assert not f1.exists() and f2.exists()        # t2 is still kept via the playlist
    assert r["keep"]["state"] == "none"
    assert k.remove_kept(conn, q, PinKind.ALBUM, "al1", starred_auto_pin=True, cache_root=tmp_path)[1]["removed_tracks"] == 0


def test_remove_kept_starred_overlap_deletes_nothing(tmp_path):
    conn = _db(tmp_path)
    reconcile_starred(conn)
    f4 = tmp_path / "t4.mp3"
    f4.write_bytes(b"x")
    _present(conn, "t4", str(f4), 1)
    k.keep(conn, None, PinKind.ALBUM, "al2")
    status, r = k.remove_kept(conn, None, PinKind.ALBUM, "al2", starred_auto_pin=True, cache_root=tmp_path)
    assert status == 200 and r["removed_tracks"] == 0 and f4.exists()
    assert r["keep"]["state"] == "starred"


def test_remove_starred_only_is_refused(tmp_path):
    conn = _db(tmp_path)
    reconcile_starred(conn)
    status, r = k.remove_kept(conn, None, PinKind.ALBUM, "al2", starred_auto_pin=True, cache_root=tmp_path)
    assert status == 409 and r == {"ok": False, "error": "unstar in Navidrome to remove"}


def test_retry_failed_requeues_pinned_failures_only(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    k.keep(conn, None, PinKind.ALBUM, "al1")
    for tid, status in (("t1", "error"), ("t2", "no_space"), ("t4", "error")):
        conn.execute("INSERT INTO cache_state(track_id,status) VALUES(?,?)", (tid, status))
    assert k.retry_failed(conn, q) == 2 and q.enqueued == ["t1", "t2"]


def test_failed_counts_follow_pins_after_remove(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    k.keep(conn, q, PinKind.ALBUM, "al1")
    conn.execute("INSERT INTO cache_state(track_id,status) VALUES('t1','error')")
    conn.execute("INSERT INTO cache_state(track_id,status) VALUES('t3','no_space')")
    conn.execute("INSERT INTO cache_state(track_id,status) VALUES('t4','error')")  # never pinned
    d = k.storage_overview(conn, None, 0, q)["downloads"]
    assert (d["failed"], d["no_space"]) == (1, 1)
    k.remove_kept(conn, q, PinKind.ALBUM, "al1", starred_auto_pin=True, cache_root=tmp_path)
    d = k.storage_overview(conn, None, 0, q)["downloads"]
    assert (d["failed"], d["no_space"]) == (0, 0)
    assert k.retry_failed(conn, q) == 0


def test_kept_tracks_counts_pinned_files_music_bytes_counts_all(tmp_path):
    conn = _db(tmp_path)
    k.keep(conn, None, PinKind.ALBUM, "al1")
    _present(conn, "t1", size=100)
    _present(conn, "t4", size=7)        # leftover streamed cache, no pin
    o = k.storage_overview(conn, None, 0, None)["drive"]
    assert o["kept_tracks"] == 1 and o["music_bytes"] == 107


def test_remove_kept_leaves_files_outside_the_cache_root(tmp_path):
    conn = _db(tmp_path)
    root, other = tmp_path / "music", tmp_path / "elsewhere"
    root.mkdir(); other.mkdir()
    inside, outside = root / "t1.mp3", other / "t3.mp3"
    inside.write_bytes(b"x" * 4)
    outside.write_bytes(b"y" * 9)
    k.keep(conn, None, PinKind.ALBUM, "al1")
    _present(conn, "t1", str(inside), 4)
    _present(conn, "t3", str(outside), 9)
    status, r = k.remove_kept(conn, None, PinKind.ALBUM, "al1", starred_auto_pin=True, cache_root=root)
    assert status == 200 and (r["removed_tracks"], r["freed_bytes"]) == (1, 4)
    assert not inside.exists() and outside.exists()
    row = conn.execute("SELECT status FROM cache_state WHERE track_id='t3'").fetchone()
    assert row[0] == "present"


def test_remove_kept_without_a_drive_deletes_nothing(tmp_path):
    conn = _db(tmp_path)
    f1 = tmp_path / "t1.mp3"
    f1.write_bytes(b"x")
    k.keep(conn, None, PinKind.ALBUM, "al1")
    _present(conn, "t1", str(f1), 1)
    r = k.remove_kept(conn, None, PinKind.ALBUM, "al1", starred_auto_pin=True, cache_root=None)[1]
    assert r["removed_tracks"] == 0 and f1.exists()
