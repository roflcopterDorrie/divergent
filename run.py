#!/usr/bin/env python3
"""No-install launcher: python3 run.py check [commit]."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from divergent.cli import main

if __name__ == "__main__":
    main()
