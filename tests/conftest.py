"""Test isolation: never write to the repository's historical ``trends.db``.

The trend tests materialize snapshots (by design), which updates trend state.
Pointing ``DATABASE_URL`` at a temporary *copy* of the committed database keeps
the real historical data byte-identical while still giving the tests the seeded
sources/entities they expect.

Set ``DATABASE_URL`` explicitly to override this behaviour (e.g. CI service DB).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_DB = REPO_ROOT / "trends.db"


def _tmp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="fashion-ai-tests-"))


if not os.environ.get("DATABASE_URL"):
    target_dir = _tmp_dir()
    target_db = target_dir / "trends.db"
    if _REPO_DB.exists():
        shutil.copy2(_REPO_DB, target_db)
    else:  # fresh checkout without the historical database
        try:
            from trend_system.bootstrap import bootstrap_trend_module

            import asyncio

            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{target_db}"
            os.environ["SYNC_DATABASE_URL"] = f"sqlite:///{target_db}"
            asyncio.run(bootstrap_trend_module(force_seed=True))
        except Exception:  # pragma: no cover - keep tests importable
            pass

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{target_db}"
    os.environ.setdefault("SYNC_DATABASE_URL", f"sqlite:///{target_db}")
