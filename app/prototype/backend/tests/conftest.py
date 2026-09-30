"""Test fixtures. The data directory is pointed at a throw-away folder BEFORE sangam is
imported, so the tests never touch the real prototype database."""
import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="sangam-test-")
os.environ["SANGAM_DATA_DIR"] = _TMP
os.environ.setdefault("SANGAM_REFERENCE_INPUT", str(Path(__file__).resolve().parents[4] / "Docs" / "input"))

import pytest  # noqa: E402

from sangam.core import config, db  # noqa: E402

REF_INPUT = Path(os.environ["SANGAM_REFERENCE_INPUT"])
needs_reference = pytest.mark.skipif(not (REF_INPUT / "batch-1").is_dir(),
                                     reason="reference inputs (Docs/input) not available")


@pytest.fixture(scope="session")
def conn():
    config.ensure_dirs()
    c = db.connect()
    yield c
    c.close()


@pytest.fixture(scope="session")
def ref(conn):
    """The April-2026 reference run, loaded once per test session."""
    if not (REF_INPUT / "batch-1").is_dir():
        pytest.skip("reference inputs (Docs/input) not available")
    from sangam.cli import load_reference
    return load_reference(conn, str(REF_INPUT), skip_exports=True, echo=lambda *_: None)
