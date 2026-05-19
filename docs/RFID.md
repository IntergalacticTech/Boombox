# RFID tap-to-play

Bind an RFID card (or NFC tag) to an album, artist, or playlist. Tap
it on the reader and the boombox starts playing. Built on top of the
[Home Library](./HOME-LIBRARY.md), so binding also pins the content
for offline play.

For the service internals see
[SERVICES.md → `boombox-rfid`](./SERVICES.md#boombox-rfid--rfid-tap--bound-playback).

---

## Hardware

Any **USB HID-keyboard RFID reader** works — the cheap $10–20 units
that show up as a generic keyboard and "type" the card UID followed
by Enter when a card is presented. Tested with:

- `ID ffff:0035 IC Reader IC Reader` (vendor:product) — common 125 kHz
  reader on Amazon, also rebranded as "USB RFID Reader" by many
  storefronts. Comes with a few EM4100 cards. Auto-detected from the
  `IC_Reader` substring in `/dev/input/by-id/*-event-kbd`.

Other reader families (13.56 MHz, ACR122U, PN532-via-USB, etc.) need
to either (a) present as a HID keyboard like the cheap ones do, or
(b) get a separate driver in `services/boombox_rfid/reader.py`.
Patches welcome.

Plug it into any free USB port. The kiosk user is added to the `input`
group at install time (`install.sh` `usermod -aG input`), so reading
the device doesn't need root. Log out and back in (or reboot) for the
group change to take effect; `id -nG` should list `input`.

---

## What happens on a tap

```
   ┌─────────┐  digits + Enter   ┌──────────────┐
   │  Card   │ ─────────────────▶│ boombox-rfid │
   └─────────┘                   │   (:6688)    │
                                 └──────┬───────┘
                          uid lookup    │
              ┌────────── in library.db ┘
              │ rfid_bindings table
              ▼
      ┌─────────────────┐
      │  Bound?         │
      └───┬─────────┬───┘
      yes │         │ no
          ▼         ▼
   ┌─────────────┐  ┌────────────────────────┐
   │ Mopidy play │  │ /api/rfid/recent       │
   │ via tlid    │  │ ┌────────────────────┐ │
   └──────┬──────┘  │ │ Kiosk overlay:     │ │
          ▼         │ │ "New card detected"│ │
       speakers     │ │ → Pick something   │ │
                    │ │   from Home Library│ │
                    │ │ → Saved + pinned   │ │
                    │ └────────────────────┘ │
                    └────────────────────────┘
```

The reader is grabbed with `EVIOCGRAB` so the digits don't leak through
to whatever window has focus on the kiosk. Same UID inside the debounce
window (default 1.5 s) is ignored — leaving a card on the reader won't
fire repeatedly.

---

## Binding a card

### From the touchscreen

1. Tap an unbound card on the reader. A modal appears:
   ```
   New card detected
   UID · 3407652605
   Tap this card to play whatever you bind it to. Pick something from
   your Home Library now.
   [ BIND TO ALBUM… ]   [ NOT NOW ]
   ```
2. Tap **BIND TO ALBUM…**. The Library drawer opens with a teal
   "BIND MODE" banner across the top, auto-navigated to **Home
   Library**.
3. Tap an album, artist, or playlist. The bind saves and a "✓ Bound
   to …" confirmation appears for ~2 s.
4. Tap the card again. The album starts playing.

Per-UID dismissal means tapping NOT NOW on a card suppresses the
prompt for that card for ~30 s. Tap a different card and the prompt
fires for it; come back to the dismissed card after 30 s and it pops
again.

### From the CLI

```bash
# Tap a card first, then ask the service what UID it saw
curl -s http://127.0.0.1/api/rfid/recent | jq

# Bind it
curl -s -X POST http://127.0.0.1/api/rfid/bind \
    -H 'Content-Type: application/json' \
    -d '{"uid":"3407652605","kind":"album","target_id":"<subsonic-album-id>","label":"AC/DC - 74 Jailbreak"}'

# List existing bindings
curl -s http://127.0.0.1/api/rfid/bindings | jq

# Unbind
curl -s -X DELETE http://127.0.0.1/api/rfid/bind/3407652605
```

You can find the Subsonic IDs in your Navidrome web UI's URL bar, or
via the CLI:

```bash
sqlite3 /opt/boombox/state/library.db \
    "SELECT id, name FROM albums WHERE name LIKE '%74 Jailbreak%'"
```

---

## What a tap actually does

Bound tap pipeline (per the data flow in
[ARCHITECTURE.md](./ARCHITECTURE.md#data-flow-home-library-tap-to-play)):

1. **`get_binding(uid)`** — single SQLite lookup.
2. **`record_tap(uid)`** — bumps `tap_count` + `last_tap_ts` so you
   can see which cards get used.
3. **`expand_to_track_ids(kind, target_id)`** — resolve the binding
   to an ordered track list:
   - **album** → tracks of that album by `(disc_no, track_no)`.
   - **artist** → tracks across all the artist's albums, ordered by
     `(album.year, album.sort_name, track.disc_no, track.track_no)`.
   - **playlist** → tracks in playlist position order.
   - **track** → that one track.
4. **`resolve_uris(tracks)`** — ask Phase 1's resolver for each
   track's playback form: `file://<cache>` when cached, direct
   Navidrome `stream.view` URL when online, dropped silently when
   offline-miss.
5. **MopidyClient.play_uris()** — `core.tracklist.clear`,
   `core.tracklist.add({uris})` (with a Track-objects fallback if
   the URI add returns empty), `core.playback.play({tlid})`, and a
   `resume` belt-and-suspenders.

---

## Pinning behaviour

Binding a card writes a Phase 1 pin row with `source='rfid'` for the
same target. That means:

- The bound content starts downloading to the cache drive (if one is
  adopted) so subsequent taps play from `file://` and don't depend on
  Navidrome being reachable.
- Pin sources rank USER > FAVORITE > RFID > STARRED. A bind doesn't
  overwrite an existing user pin; an explicit user pin DOES overwrite
  an RFID-source pin.
- Unbinding source-filters the RFID pin only — if you've also
  explicitly pinned the album, that user pin survives the unbind.

---

## Config (`/etc/boombox/rfid.yml`)

```yaml
enabled: true              # set false to skip the reader loop entirely
device_path: ""            # empty → auto-detect by alias substring
debounce_ms: 1500          # same UID within this window is ignored
recent_ttl_ms: 30000       # how long an unbound UID stays in /recent
mopidy_rpc: "http://127.0.0.1:6680/mopidy/rpc"
```

`device_path: ""` makes the service scan `/dev/input/by-id/` for any
`-event-kbd` alias containing `IC_Reader` (case-insensitive) or
`RFID`. For a non-matching reader, pin the path explicitly:

```yaml
device_path: "/dev/input/by-id/usb-Some_Vendor_Some_Model-event-kbd"
```

After editing, `systemctl --user restart boombox-rfid`.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Service running but no taps appear in the log | Card actually scanned? Check the UID isn't being typed into Chromium (means EVIOCGRAB failed — log says `EVIOCGRAB failed (...)`; check the user is in the `input` group). |
| `journalctl --user -u boombox-rfid` shows "no RFID reader device detected" | Reader not plugged in, OR the udev alias doesn't match. `ls /dev/input/by-id/*-event-kbd` to see all keyboards. Pin the right one via `device_path:` in `/etc/boombox/rfid.yml`. |
| Tap log appears but Mopidy state stays unchanged | Mopidy scan patch missing — see the Trixie note in [SERVICES.md → `boombox-rfid`](./SERVICES.md#boombox-rfid--rfid-tap--bound-playback). |
| Bound tap plays but only one track for an artist | Your Navidrome catalog only has one track for that artist. Check `sqlite3 /opt/boombox/state/library.db "SELECT id, name FROM albums WHERE artist_id=?"`. |
| Bind succeeded but the UI is stuck on "Binding…" | The library service was holding the SQLite writer lock during sync. Should resolve in <1 s as of `f6ee071`; if stuck for longer, `journalctl --user -u boombox-library -n 50` for clues. |
| Card taps fire for the LAST UID over and over | A previous unbound tap is still inside `recent_ttl_ms`. Either bind it, or wait 30 s. |

---

## Roadmap

- **PWA bindings page** — list / bind / unbind from the phone. Backend
  already supports this (`/api/rfid/*` is unauthenticated within the
  proxy; the PWA just needs the view).
- **Long-press to manage a bound card** — show binding metadata
  (label, tap count, last tap timestamp) and an unbind button in the
  same modal that the bind overlay uses.
- **Per-card volume preset** — interesting once we have kid-facing
  cards.
