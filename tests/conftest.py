"""Root pytest config.

Adds `src/` to sys.path so tests can `import lexicon.discover.*`.

IMPORTANT — Do NOT add `__init__.py` files under `tests/lexicon/` or any of
its subdirectories. Doing so causes pytest to treat `tests/lexicon/` as a
package named `lexicon`, which then shadows the production package at
`src/lexicon/` (both are visible on sys.path). Tests under `tests/lexicon/`
must be namespace packages (no `__init__.py`) so imports resolve to the
production code they are testing.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
