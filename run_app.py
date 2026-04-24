#!/usr/bin/env python3
"""Run MarketMetrics desktop app from project root."""
import os
import sys
from pathlib import Path

import faulthandler

# Ensure project root is on path.
root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

faulthandler.enable()

debug_dump_after_sec = os.environ.get("MARKETMETRICS_DEBUG_DUMP_AFTER_SEC")
if debug_dump_after_sec:
    import threading

    def dump() -> None:
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)

    try:
        delay = float(debug_dump_after_sec)
    except ValueError:
        delay = 0.0

    if delay > 0:
        threading.Timer(delay, dump).start()

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
