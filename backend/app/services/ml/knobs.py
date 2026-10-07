"""One tunable of a catalog algorithm, typed so a form can render it.

Bounds are part of the contract, not a UI convenience: they are what keeps a
no-code form from producing a fit that runs for an hour. Each kind coerces a
submitted value into its own domain rather than refusing it, because a form
that drifted (an old tab, a hand-written Flow node) should still train the
nearest sane model, and the coerced value is what the card then shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

KNOB_KINDS = ("int", "float", "enum", "bool", "int_list")
_NUMERIC = frozenset({"int", "float"})
_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True, slots=True)
class Knob:
    """One tunable of an algorithm, with the bounds the UI renders as a field.

    ``int``/``float`` are sliders between ``minimum`` and ``maximum``;
    ``enum`` picks one of ``choices``; ``bool`` is a toggle; ``int_list`` is a
    short list of bounded integers (lags, seasonal periods), at most
    ``max_items`` long.
    """

    key: str
    kind: str  # int | float | enum | bool | int_list
    default: Any
    minimum: float = 0.0
    maximum: float = 0.0
    step: float = 1.0
    # Sentinel meaning "let the estimator decide" (sklearn's ``None``).
    auto_at: float | None = None
    choices: tuple[str, ...] = ()
    max_items: int = 0

    def __post_init__(self) -> None:
        if self.kind not in KNOB_KINDS:
            raise ValueError(f"knob {self.key}: unknown kind {self.kind!r}")
        if self.kind in _NUMERIC and not self.minimum <= self.default <= self.maximum:
            raise ValueError(f"knob {self.key}: default outside its bounds")
        if self.kind == "enum" and self.default not in self.choices:
            raise ValueError(f"knob {self.key}: default is not one of its choices")
        if self.kind == "bool" and not isinstance(self.default, bool):
            raise ValueError(f"knob {self.key}: a bool knob needs a bool default")
        if self.kind == "int_list":
            items = tuple(self.default)
            if self.max_items < 1 or not items or len(items) > self.max_items:
                raise ValueError(f"knob {self.key}: default list length out of range")
            if any(not self.minimum <= item <= self.maximum for item in items):
                raise ValueError(f"knob {self.key}: default item outside its bounds")

    def coerce(self, value: Any) -> Any:
        if self.kind == "enum":
            return value if isinstance(value, str) and value in self.choices else self.default
        if self.kind == "bool":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            return True if text in _TRUE else False if text in _FALSE else self.default
        if self.kind == "int_list":
            return self._coerce_list(value)
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float(self.default)
        number = max(self.minimum, min(self.maximum, number))
        if self.auto_at is not None and number == self.auto_at:
            return None
        return int(round(number)) if self.kind == "int" else round(number, 6)

    def _coerce_list(self, value: Any) -> list[int]:
        if not isinstance(value, (list, tuple)):
            return list(self.default)
        items: set[int] = set()
        for item in value:
            if isinstance(item, bool):
                continue
            try:
                number = int(round(float(item)))
            except (TypeError, ValueError):
                continue
            items.add(int(max(self.minimum, min(self.maximum, number))))
        return sorted(items)[: self.max_items] or list(self.default)

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "key": self.key,
            "kind": self.kind,
            "default": list(self.default) if self.kind == "int_list" else self.default,
        }
        if self.kind in _NUMERIC or self.kind == "int_list":
            body.update({"min": self.minimum, "max": self.maximum, "step": self.step})
        if self.auto_at is not None:
            body["auto_at"] = self.auto_at
        if self.kind == "enum":
            body["choices"] = list(self.choices)
        if self.kind == "int_list":
            body["max_items"] = self.max_items
        return body
