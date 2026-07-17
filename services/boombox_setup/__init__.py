"""boombox-setup — first-run setup wizard backend (port 6689, nginx /api/setup/).

The single front-door the setup wizard talks to from BOTH the kiosk
(localhost, trusted) and a phone/laptop browser (LAN, setup-token gated). It
orchestrates the privileged bits via the root helper
(/usr/local/sbin/boombox-setup-apply) and proxies music/remote config to the
existing boombox-library and boombox-remote services over loopback so the
phone never has to clear LAN Basic auth.
"""

__version__ = "0.1.0"
