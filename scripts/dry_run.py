"""Run the full pipeline locally and print the digest to stdout.

Usage:
    JARVIS_DRY_RUN=true python scripts/dry_run.py
"""

import asyncio
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis.__main__ import main

if __name__ == "__main__":
    main()
