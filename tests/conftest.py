"""Add repo root to sys.path so tests can import project modules directly."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
