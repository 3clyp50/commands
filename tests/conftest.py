# tests/conftest.py
import sys
from pathlib import Path

# Ensure A0 framework root is first in sys.path so that
# `from helpers import ...` resolves to A0's helpers/, not
# the Commands plugin's local helpers/ directory.
a0_root = str(Path(__file__).resolve().parents[3])  # tests/ → plugin → plugins → usr → a0
if a0_root not in sys.path:
    sys.path.insert(0, a0_root)
