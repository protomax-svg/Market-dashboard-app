#!/usr/bin/env python3
"""Run MarketMetrics desktop app from project root."""
import sys
from pathlib import Path

# Ensure project root is on path
root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import faulthandler, sys, threading
faulthandler.enable()

def dump():
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)

threading.Timer(5.0, dump).start()

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
