"""Persisted runtime state for boombox-updater.

Lives at /opt/boombox/state/updater.json (with a sibling logs/ dir for
per-attempt install logs). The file is the source of truth for the UI
and CLI — always atomic-write, never partial.
"""
from __future__ import annotations

import enum
import json
import os
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Optional

DEFAULT_STATE_DIR = Path("/opt/boombox/state")
LOG_KEEP = 10  # how many per-attempt logs to retain


class AttemptResult(str, enum.Enum):
    OK = "ok"
    ROLLED_BACK = "rolled_back"
    BROKEN = "broken"           # rollback itself failed
    SKIPPED_PLAYBACK = "skipped_playback"
    FETCH_FAILED = "fetch_failed"
    BUILD_FAILED = "build_failed"
    SMOKE_FAILED = "smoke_failed"


@dataclass(frozen=True)
class LastAttempt:
    ts: float
    ref: str
    result: AttemptResult
    error: Optional[str]
    log_path: str  # relative to state dir


@dataclass(frozen=True)
class State:
    installed_version: str
    available_version: str
    available_published_at: str
    last_check_ts: float
    last_attempt: Optional[LastAttempt]
    state_machine: str  # "idle" | "fetching" | "building" | ... | "broken"


EMPTY_STATE = State(
    installed_version="unknown",
    available_version="",
    available_published_at="",
    last_check_ts=0.0,
    last_attempt=None,
    state_machine="idle",
)


def _serialize(state: State) -> dict:
    payload = asdict(state)
    if state.last_attempt is not None:
        payload["last_attempt"]["result"] = state.last_attempt.result.value
    return payload


def _deserialize(raw: dict) -> State:
    raw_attempt = raw.get("last_attempt")
    last_attempt: Optional[LastAttempt] = None
    if raw_attempt:
        last_attempt = LastAttempt(
            ts=float(raw_attempt["ts"]),
            ref=str(raw_attempt["ref"]),
            result=AttemptResult(raw_attempt["result"]),
            error=raw_attempt.get("error"),
            log_path=str(raw_attempt.get("log_path", "")),
        )
    return State(
        installed_version=str(raw.get("installed_version", "unknown")),
        available_version=str(raw.get("available_version", "")),
        available_published_at=str(raw.get("available_published_at", "")),
        last_check_ts=float(raw.get("last_check_ts", 0.0)),
        last_attempt=last_attempt,
        state_machine=str(raw.get("state_machine", "idle")),
    )


class StateStore:
    def __init__(self, state_dir: Path = DEFAULT_STATE_DIR) -> None:
        self._dir = state_dir
        self._file = state_dir / "updater.json"
        self._logs = state_dir / "logs"

    def load(self) -> State:
        """Load state, returning EMPTY_STATE on missing/corrupt/unreadable
        files. Catches OSError broadly (covers FileNotFoundError,
        PermissionError, broken symlinks) so a read failure can never
        crash the service."""
        try:
            raw = json.loads(self._file.read_text())
        except (OSError, json.JSONDecodeError):
            return EMPTY_STATE
        try:
            return _deserialize(raw)
        except (KeyError, ValueError, TypeError):
            return EMPTY_STATE

    def save(self, state: State) -> None:
        """Atomically write state (.tmp + rename, fsync)."""
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".json.tmp")
        payload = json.dumps(_serialize(state), indent=2, sort_keys=True) + "\n"
        with tmp.open("w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self._file)

    def update(self, **fields) -> State:
        """Merge fields into the persisted state and return the new value."""
        new = replace(self.load(), **fields)
        self.save(new)
        return new

    def new_log_path(self, ref: str) -> Path:
        """Return a fresh (non-existent) per-attempt log path under logs/.
        The caller is responsible for opening/writing it."""
        self._logs.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H%M%S")
        safe_ref = ref.replace("/", "_")
        return self._logs / f"{ts}-{safe_ref}.log"

    def prune_logs(self, keep: int = LOG_KEEP) -> None:
        """Delete all but the newest `keep` per-attempt logs. Logs are
        named with a sortable %Y-%m-%dT%H%M%S prefix, so lexical sort by
        name is chronological."""
        if not self._logs.is_dir():
            return
        files = sorted(self._logs.iterdir(), key=lambda p: p.name)
        for old in files[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
