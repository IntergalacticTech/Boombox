# install/legacy

The files in here were the **manual** path to building a Boombox before the
unified `install/install.sh` existed. They're kept for reference (and as a
fallback in case the new installer breaks on some unexpected Pi OS variant).

| File | What it was for | Replaced by |
|------|-----------------|-------------|
| `manual-walkthrough.md` | Step-by-step shell-by-shell install notes | `install/install.sh` (idempotent installer) |
| `setup_auto_resume.sh`  | Mopidy queue save/restore via mpc + systemd | `boombox-resume` service + `install/systemd/user/boombox-resume.service` |
| `setup_playback.sh`     | First pass at Mopidy + autoresume via legacy plugins (Mopidy-Local-SaveState, Mopidy-Autoplay) | `install/install.sh` + `boombox-resume` |

Do not run these on a host that has the new installer already applied —
they'll fight with the systemd units and configs in `install/`.
