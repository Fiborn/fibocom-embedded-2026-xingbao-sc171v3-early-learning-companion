import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .events import EventName


class JsonlEventLogger:
    def __init__(self, log_dir=None, session_id=None):
        self.log_dir = Path(log_dir or "logs")
        self.session_id = session_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
        self.path = self.log_dir / "session_{}.jsonl".format(self.session_id)
        self.last_error = None
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.last_error = str(exc)

    def log(self, event_name, page, payload=None, game_id=None):
        if isinstance(event_name, EventName):
            event_name = event_name.value
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "session_id": self.session_id,
            "event_name": event_name,
            "page": page,
            "game_id": game_id,
            "payload": payload or {},
        }
        try:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.last_error = None
            return self.path
        except OSError as exc:
            self.last_error = str(exc)
            return None
