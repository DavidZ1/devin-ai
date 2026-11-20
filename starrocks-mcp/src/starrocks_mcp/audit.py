from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from typing import Any

from .config import Settings

_lock = threading.Lock()


def record_event(settings: Settings, **event: Any) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    line = json.dumps(entry, ensure_ascii=False, default=str)
    with _lock:
        print(line, file=sys.stderr, flush=True)
        if settings.audit_log_file:
            try:
                with open(settings.audit_log_file, "a", encoding="utf-8") as output:
                    output.write(line + "\n")
            except OSError as exc:
                print(f"Could not write audit log: {exc}", file=sys.stderr, flush=True)
