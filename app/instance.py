from __future__ import annotations

import hashlib
from pathlib import Path


APP_ID = "a_share_intraday_radar"


def root_fingerprint(root: Path) -> str:
    normalized = str(root.resolve()).casefold().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:16]
