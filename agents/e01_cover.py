"""Compat: capa do E01."""
import os
os.environ.setdefault("VNC_EPISODE", "E01")
import agents.vnc_cover  # noqa: F401  (executa no import, como antes)
