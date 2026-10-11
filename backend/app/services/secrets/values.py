"""Opaque secret values and registry errors.

``SecretValue`` wraps a clear-text secret so it cannot leak by accident:
``str``/``repr``/``format`` render ``***``, JSON and pickle serialisation raise
``TypeError``. The only way to read the value is ``SecretValue.reveal()``;
call it at the last moment (building a header, opening a connection) and
never store the result.

``SecretRegistryError.code`` is a stable machine code callers can map to HTTP
or flow errors: ``SECRET_INVALID_REF``, ``SECRET_INVALID``,
``SECRET_NAME_TAKEN``, ``SECRET_NOT_FOUND``, ``SECRET_DISABLED``,
``SECRET_EXPIRED``, ``SECRET_VERSION_DESTROYED``, ``SECRET_SCOPE_VIOLATION``,
``SECRET_BACKEND_UNAVAILABLE``, ``SECRET_KEY_NOT_CONFIGURED``. Messages never
contain secret values.
"""

from __future__ import annotations

import hmac

MASK = "***"


class SecretRegistryError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


class SecretValue:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("SecretValue wraps a str")
        object.__setattr__(self, "_value", value)

    def reveal(self) -> str:
        return self._value

    def __setattr__(self, name, value):  # noqa: ANN001
        raise AttributeError("SecretValue is immutable")

    def __repr__(self) -> str:
        return f"SecretValue({MASK})"

    def __str__(self) -> str:
        return MASK

    def __format__(self, spec: str) -> str:
        return MASK

    def __len__(self) -> int:
        return len(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretValue):
            return NotImplemented
        return hmac.compare_digest(self._value.encode(), other._value.encode())

    __hash__ = None  # type: ignore[assignment]

    def __reduce__(self):
        raise TypeError("SecretValue cannot be pickled")

    def __reduce_ex__(self, protocol):  # noqa: ANN001
        raise TypeError("SecretValue cannot be pickled")

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):  # noqa: ANN001
        return self

    def __json__(self):
        raise TypeError("SecretValue is not JSON serialisable")
