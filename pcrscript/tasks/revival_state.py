"""Per-account, per-occurrence completion receipts; partial runs remain resumable."""
from .base import Event, TaskReport
from ..run_session import atomic_json
import hashlib
import json
from pathlib import Path


class RevivalState:
    def __init__(self, root: str | Path, account: str | int, event: Event) -> None:
        scope = hashlib.sha256(str(account).encode()).hexdigest()[:16]
        event_id = int(event.extras['event_id'])
        self.path = Path(root) / scope / f'{event_id}-{int(event.startTimestamp)}.json'
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}

    @property
    def complete(self) -> bool:
        return self.data.get('status') == 'complete'

    def save(self, report: TaskReport) -> None:
        atomic_json(self.path, report)
        self.data = report
