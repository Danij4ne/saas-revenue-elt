"""Package entrypoint so the pipeline runs as ``python -m src``.

Kept intentionally trivial: all parsing/dispatch lives in ``src.cli`` so it can
be unit-tested without spawning a process.
"""

from __future__ import annotations

from src.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
