"""Server-only return type: native submission succeeded, waiting is external."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DeferredNativeExecution:
    kind: Literal["recipe_execution"]
    id: str
