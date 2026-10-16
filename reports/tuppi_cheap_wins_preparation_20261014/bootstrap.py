"""Import only this package's captured AI and authoritative current engine."""
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent


def activate():
    if any(x in sys.modules for x in ("tuppi_ai", "tuppi_engine", "tuppi_rules")):
        raise RuntimeError("Activate snapshot before any Tuppi import")
    sys.path[:0] = [str(OUT / "runtime"), str(OUT / "frozen/engine/src")]
