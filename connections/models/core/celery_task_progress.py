from dataclasses import dataclass
from typing import Literal

type CoreStatusesFinal = Literal["available", "error", "cancelled"]
type CoreStatuses = Literal["waiting", "running", "available", "error", "cancelled"]


@dataclass(slots=True)
class CeleryTaskProgressToCore:
    id: str
    """ID of the db record which is used in the core."""
    status: CoreStatuses
    """Status of the task."""
    logs: str
    """Logs of the task. We also use this field to store the progress message."""
