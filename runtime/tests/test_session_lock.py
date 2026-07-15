import tempfile
from pathlib import Path

from runtime.session import ProfileLock


def test_profile_lock_exclusive():
    d = Path(tempfile.mkdtemp())
    with ProfileLock(d) as L1:
        raised = False
        try:
            with ProfileLock(d, timeout=0.2):
                pass
        except TimeoutError:
            raised = True
        assert raised
