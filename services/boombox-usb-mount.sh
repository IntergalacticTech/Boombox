#!/usr/bin/env bash
# boombox-usb-mount.sh — mount a USB partition into the boombox library.
#
# Called by systemd unit boombox-usb-mount@<sd-escaped-dev>.service when a
# new USB block device with a filesystem appears. Two modes:
#
#   $0 mount   <device>     mount $device under /media/boombox/<id>, symlink
#                           it under $BOOMBOX_USER_HOME/Music/.usb/<id>,
#                           trigger a Mopidy rescan
#   $0 unmount <device>     reverse the above
#
# Runs as root (block-device access). Filesystem ownership maps to the
# boombox user via the mount's uid/gid options where the FS supports it
# (vfat/exfat/ntfs).
#
# id is derived from the partition LABEL when present, otherwise the UUID.

set -euo pipefail

# NB: the parameter-expansion error message is plain text — including the
# canonical "{mount|unmount}" usage hint here would unbalance bash's brace
# parser and chop the message into $1/$2 as literals. Don't put { } in :?.
ACTION="${1:?usage: see top of script (mount or unmount, then a /dev/sdXY)}"
DEVICE="${2:?usage: see top of script (mount or unmount, then a /dev/sdXY)}"

# Where to look up the boombox desktop user. install.sh writes this.
USER_FILE=/etc/boombox/desktop-user
if [[ ! -r "$USER_FILE" ]]; then
  echo "error: $USER_FILE missing — run install.sh on this Pi first" >&2
  exit 1
fi
BBX_USER="$(cat "$USER_FILE")"
BBX_UID="$(id -u "$BBX_USER")"
BBX_GID="$(id -g "$BBX_USER")"
BBX_HOME="$(getent passwd "$BBX_USER" | cut -d: -f6)"
MUSIC_ROOT="$BBX_HOME/Music"
VIDEO_ROOT="$BBX_HOME/Videos"
USB_LINKS_DIR="$MUSIC_ROOT/.usb"
VIDEO_USB_LINKS_DIR="$VIDEO_ROOT/.usb"

log() { logger -t boombox-usb "$*"; echo "[boombox-usb] $*" >&2; }

# ---------------------------------------------------------------------------
# Identify the device
# ---------------------------------------------------------------------------
get_id() {
  local label uuid
  label="$(blkid -o value -s LABEL "$DEVICE" 2>/dev/null || true)"
  uuid="$(blkid  -o value -s UUID  "$DEVICE" 2>/dev/null || true)"
  if [[ -n "$label" ]]; then
    # sanitize: only [A-Za-z0-9_-]; everything else becomes '_'
    echo "$label" | tr -c 'A-Za-z0-9_-' '_'
  elif [[ -n "$uuid" ]]; then
    echo "usb-${uuid:0:8}"
  else
    echo "usb-$(echo "$DEVICE" | tr '/' '_')"
  fi
}

ID="$(get_id)"
MOUNTPOINT="/media/boombox/$ID"
LINK="$USB_LINKS_DIR/$ID"
VIDEO_LINK="$VIDEO_USB_LINKS_DIR/$ID"

trigger_scan() {
  # boombox-state has /library/scan on 127.0.0.1:6681; if it's down, fall
  # back to mopidyctl directly.
  if curl -fsS -X POST -m 2 http://127.0.0.1:6681/library/scan >/dev/null 2>&1; then
    :
  elif command -v mopidyctl >/dev/null 2>&1; then
    mopidyctl local scan >/dev/null 2>&1 &
  fi

  # Nudge Jellyfin too. The default token-less endpoint is gated, so we
  # use the configured api-key from /etc/boombox/jellyfin-api-key if
  # present; otherwise we skip. Jellyfin's "real-time monitoring" picks
  # up the new symlinks on its own within ~10s anyway.
  local key_file=/etc/boombox/jellyfin-api-key
  if [[ -r "$key_file" ]]; then
    local key
    key=$(cat "$key_file")
    curl -fsS -m 3 -X POST \
      -H "X-MediaBrowser-Token: $key" \
      "http://127.0.0.1:8096/Library/Refresh" >/dev/null 2>&1 || true
  fi
}

# ---------------------------------------------------------------------------
case "$ACTION" in

  mount)
    if [[ ! -b "$DEVICE" ]]; then
      log "no such block device: $DEVICE — aborting"
      exit 1
    fi

    fstype="$(blkid -o value -s TYPE "$DEVICE" 2>/dev/null || echo unknown)"
    log "mounting $DEVICE ($fstype) → $MOUNTPOINT"

    mkdir -p "$MOUNTPOINT" "$USB_LINKS_DIR" "$VIDEO_USB_LINKS_DIR"
    chown "$BBX_USER:$BBX_USER" "$USB_LINKS_DIR" "$VIDEO_USB_LINKS_DIR" 2>/dev/null || true

    # Already mounted? (udev fires multiple events on some devices.)
    if mountpoint -q "$MOUNTPOINT"; then
      log "already mounted — refreshing symlink only"
    else
      mount_opts="ro,nosuid,nodev,noatime"
      case "$fstype" in
        vfat|exfat)
          mount_opts="${mount_opts},uid=${BBX_UID},gid=${BBX_GID},umask=022"
          ;;
        ntfs|fuseblk)
          # Pi OS ships ntfs3 (kernel) which doesn't take uid/gid; the userspace
          # ntfs-3g does. Try kernel first, fall back to FUSE.
          if mount -t ntfs3 -o "$mount_opts" "$DEVICE" "$MOUNTPOINT" 2>/dev/null; then
            log "mounted ntfs3 ok"
          else
            mount -t ntfs-3g -o "${mount_opts},uid=${BBX_UID},gid=${BBX_GID}" "$DEVICE" "$MOUNTPOINT"
            log "fell back to ntfs-3g"
          fi
          ;;
      esac
      if ! mountpoint -q "$MOUNTPOINT"; then
        mount -o "$mount_opts" "$DEVICE" "$MOUNTPOINT"
      fi
    fi

    # Symlink into each library root so Mopidy + Jellyfin recursive scans
    # pick the drive up. Mopidy's local scanner follows symlinks by default;
    # Jellyfin needs to be configured to allow symlinked content (done in
    # install.sh).
    ln -snf "$MOUNTPOINT" "$LINK"
    ln -snf "$MOUNTPOINT" "$VIDEO_LINK"
    chown -h "$BBX_USER:$BBX_USER" "$LINK" "$VIDEO_LINK" 2>/dev/null || true

    trigger_scan
    log "mounted $ID"
    ;;

  unmount)
    log "unmounting $DEVICE (id=$ID)"
    rm -f "$LINK" "$VIDEO_LINK"
    if mountpoint -q "$MOUNTPOINT"; then
      umount "$MOUNTPOINT" || umount -l "$MOUNTPOINT" || true
    fi
    rmdir "$MOUNTPOINT" 2>/dev/null || true
    trigger_scan
    log "unmounted $ID"
    ;;

  *)
    echo "usage: $0 {mount|unmount} <device>" >&2
    exit 1
    ;;
esac
