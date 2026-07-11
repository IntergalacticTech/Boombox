"""BLE GATT peripheral for the wireless-remote service.

Exposes a custom service over BLE so ESP32 remotes (CYD, ELECROW, headless
DIY, etc.) can pair, subscribe to state pushes, and dispatch commands
without depending on WiFi being available or configured.

The PIN flow is shared with the HTTP path: a kiosk-side overlay calls
POST /api/remote/pair/start (localhost-only) to mint a PIN; the CYD then
writes that PIN to the BLE `pair_request` characteristic and receives the
auth token via notify on `pair_response`. State and commands have their
own characteristics.

Service UUID: 0000bbbb-0000-1000-8000-00805f9b34fb
Characteristics:
    0000bbbe-...   device_info   (read)        JSON
    0000bbb1-...   pair_request  (write)       UTF-8 PIN
    0000bbb2-...   pair_response (notify+read) JSON {ok, auth_token, ...}
    0000bbb3-...   state         (notify+read) JSON consolidated state
    0000bbb4-...   command       (write)       JSON {action, value?}

Backed by `bless` (cross-platform BLE peripheral lib that wraps BlueZ on
Linux via dbus-fast). Earlier attempt with `bluez_peripheral` hit a
dbus_next introspection incompatibility on BlueZ 5.82.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from bless import (
    BlessGATTCharacteristic,
    BlessServer,
    GATTAttributePermissions,
    GATTCharacteristicProperties,
)

log = logging.getLogger("boombox-remote-ble")

SERVICE_UUID       = "0000bbbb-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_UUID   = "0000bbbe-0000-1000-8000-00805f9b34fb"
PAIR_REQUEST_UUID  = "0000bbb1-0000-1000-8000-00805f9b34fb"
PAIR_RESPONSE_UUID = "0000bbb2-0000-1000-8000-00805f9b34fb"
STATE_UUID         = "0000bbb3-0000-1000-8000-00805f9b34fb"
COMMAND_UUID       = "0000bbb4-0000-1000-8000-00805f9b34fb"


class BoomboxBlePeripheral:
    """Wraps a BlessServer for the boombox-remote BLE protocol."""

    def __init__(self, *,
                 pair_state: dict,
                 peers_path_cb: Callable[[], str],
                 hash_pin_cb: Callable[[str], str],
                 aggregator: Any,
                 dispatcher: Any,
                 fire_cb: Callable[..., Awaitable[Any]],
                 boombox_id: str,
                 boombox_name: str):
        self._pair_state     = pair_state
        self._peers_path_cb  = peers_path_cb
        self._hash_pin_cb    = hash_pin_cb
        self._aggregator     = aggregator
        self._dispatcher     = dispatcher
        self._fire_cb        = fire_cb
        self._boombox_id     = boombox_id
        self._boombox_name   = boombox_name
        self._server: Optional[BlessServer] = None
        self._last_state_json: bytes = b'{"ok":false}'
        self._last_pair_resp: bytes  = b'{"ok":false,"error":"no_response_yet"}'
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _read_cb(self, characteristic: BlessGATTCharacteristic, **kw) -> bytes:
        uuid = characteristic.uuid.lower()
        if uuid == DEVICE_INFO_UUID:
            return json.dumps({
                "id": self._boombox_id,
                "name": self._boombox_name,
                "version": 1,
            }).encode()
        if uuid == PAIR_RESPONSE_UUID:
            return self._last_pair_resp
        if uuid == STATE_UUID:
            return self._last_state_json
        return b""

    def _write_cb(self, characteristic: BlessGATTCharacteristic,
                  value: bytes, **kw):
        uuid = characteristic.uuid.lower()
        if uuid == PAIR_REQUEST_UUID:
            self._handle_pair_write(value)
        elif uuid == COMMAND_UUID:
            self._handle_command_write(value)
        else:
            log.debug("[ble] write to unhandled char %s", uuid)

    # --- pair_request handler --------------------------------------------
    def _handle_pair_write(self, value: bytes):
        try:
            pin = value.decode("ascii").strip()
        except Exception:
            self._set_pair_response({"ok": False, "error": "bad_pin"})
            return
        if len(pin) != 6 or not pin.isdigit():
            self._set_pair_response({"ok": False, "error": "bad_pin"})
            return
        st = self._pair_state
        if st["pin_hash"] is None or time.time() > st["expires_at"]:
            self._set_pair_response({"ok": False, "error": "no_active_pin"})
            return
        if not hmac.compare_digest(self._hash_pin_cb(pin), st["pin_hash"]):
            self._set_pair_response({"ok": False, "error": "bad_pin"})
            return
        # Verified — single-use, invalidate now.
        st["pin_hash"] = None
        st["expires_at"] = 0

        token = secrets.token_hex(32)
        path = Path(self._peers_path_cb())
        try:
            peers = json.loads(path.read_text())
        except Exception:
            peers = {}
        peers[token] = {"label": "ble-paired", "paired_at": int(time.time())}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(peers, indent=2))
        log.info("[ble] paired peer")

        self._set_pair_response({
            "ok": True,
            "auth_token":   token,
            "boombox_id":   self._boombox_id,
            "boombox_name": self._boombox_name,
        })

    def _set_pair_response(self, payload: dict):
        self._last_pair_resp = json.dumps(payload).encode()
        if self._server:
            try:
                # Update char value + push notify to subscribers.
                c = self._server.get_characteristic(PAIR_RESPONSE_UUID)
                if c is not None:
                    c.value = self._last_pair_resp
                self._server.update_value(SERVICE_UUID, PAIR_RESPONSE_UUID)
            except Exception as e:
                log.warning("[ble] pair_response notify failed: %s", e)

    # --- command handler -------------------------------------------------
    def _handle_command_write(self, value: bytes):
        try:
            req = json.loads(value.decode("utf-8"))
        except Exception:
            log.warning("[ble] command: invalid JSON")
            return
        action = req.get("action")
        if not isinstance(action, str):
            log.warning("[ble] command: missing action")
            return
        cmd_value = req.get("value")
        log.info("[ble] command action=%s value=%r", action, cmd_value)
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._fire_cb(self._dispatcher, action, cmd_value,
                                source="ble"),
                self._loop,
            )

    # --- state push loop -------------------------------------------------
    async def _push_state_loop(self, interval_s: float = 0.5):
        while True:
            try:
                data = await self._aggregator.consolidated_state()
                payload = json.dumps({"ok": True, "data": data}, default=str,
                                      sort_keys=True).encode()
                if payload != self._last_state_json:
                    self._last_state_json = payload
                    try:
                        c = self._server.get_characteristic(STATE_UUID)
                        if c is not None:
                            c.value = payload
                        self._server.update_value(SERVICE_UUID, STATE_UUID)
                    except Exception as e:
                        log.debug("[ble] state notify: %s", e)
            except Exception as e:
                log.warning("[ble] state poll error: %s", e)
            await asyncio.sleep(interval_s)

    # --- lifecycle -------------------------------------------------------
    async def start(self):
        self._loop = asyncio.get_running_loop()
        self._server = BlessServer(name=self._boombox_name)
        self._server.read_request_func = self._read_cb
        self._server.write_request_func = self._write_cb

        await self._server.add_new_service(SERVICE_UUID)

        # device_info: read-only.
        await self._server.add_new_characteristic(
            SERVICE_UUID, DEVICE_INFO_UUID,
            GATTCharacteristicProperties.read,
            b"{}",
            GATTAttributePermissions.readable,
        )
        # pair_request: write-only.
        await self._server.add_new_characteristic(
            SERVICE_UUID, PAIR_REQUEST_UUID,
            GATTCharacteristicProperties.write
            | GATTCharacteristicProperties.write_without_response,
            b"",
            GATTAttributePermissions.writeable,
        )
        # pair_response: read + notify.
        await self._server.add_new_characteristic(
            SERVICE_UUID, PAIR_RESPONSE_UUID,
            GATTCharacteristicProperties.read
            | GATTCharacteristicProperties.notify,
            self._last_pair_resp,
            GATTAttributePermissions.readable,
        )
        # state: read + notify.
        await self._server.add_new_characteristic(
            SERVICE_UUID, STATE_UUID,
            GATTCharacteristicProperties.read
            | GATTCharacteristicProperties.notify,
            self._last_state_json,
            GATTAttributePermissions.readable,
        )
        # command: write-only.
        await self._server.add_new_characteristic(
            SERVICE_UUID, COMMAND_UUID,
            GATTCharacteristicProperties.write
            | GATTCharacteristicProperties.write_without_response,
            b"",
            GATTAttributePermissions.writeable,
        )

        await self._server.start()
        log.info("[ble] advertising as %s with service %s",
                  self._boombox_name, SERVICE_UUID)

        # Start the state push loop. Returns the task so caller can cancel.
        return asyncio.create_task(self._push_state_loop())

    async def stop(self):
        if self._server:
            try:
                await self._server.stop()
            except Exception as e:
                log.warning("[ble] stop: %s", e)
            self._server = None


async def run_ble_peripheral(*, pair_state, peers_path_cb, hash_pin_cb,
                              aggregator, dispatcher, fire_cb,
                              boombox_id, boombox_name, pair_ttl_s=120):
    """Start the BLE peripheral. Runs forever (or until cancelled)."""
    peripheral = BoomboxBlePeripheral(
        pair_state=pair_state,
        peers_path_cb=peers_path_cb,
        hash_pin_cb=hash_pin_cb,
        aggregator=aggregator,
        dispatcher=dispatcher,
        fire_cb=fire_cb,
        boombox_id=boombox_id,
        boombox_name=boombox_name,
    )
    push_task = await peripheral.start()
    try:
        await push_task
    except asyncio.CancelledError:
        await peripheral.stop()
        raise
