"""Small structured telemetry; no provider credentials or URLs are logged."""
import json
import logging
import time
import uuid

IMPORT_STARTED = time.perf_counter()
IMPORT_MS = 0.0
INSTANCE_ID = uuid.uuid4().hex[:12]
REQUEST_COUNT = 0


def log_event(event, **fields):
    logging.getLogger("market_regime").warning(json.dumps({"event": event, **fields}, separators=(",", ":")))
