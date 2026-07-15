from __future__ import annotations

import json
import time
from typing import Any

from runtime import paths


def audit(event: str, **fields: Any) -> None:
    """Append one JSON line to paths.AUDIT_LOG."""
    paths.ensure_data_dirs()
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **fields}
    with paths.AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
