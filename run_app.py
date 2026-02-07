#!/usr/bin/env python3
"""Run MarketMetrics desktop app from project root."""
import sys
from pathlib import Path

# Ensure project root is on path
root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
