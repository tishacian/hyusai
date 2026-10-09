"""The model families the platform can train, and how to find one."""

from __future__ import annotations

from app.services.ml.families.base import Family, SpecField, SpecInvalid
from app.services.ml.families.forecasting import FORECASTING_FAMILY
from app.services.ml.families.tabular import TABULAR
from app.services.ml.families.forecasting_deep import FORECASTING_DEEP

FAMILIES: tuple[Family, ...] = (TABULAR, FORECASTING_FAMILY, FORECASTING_DEEP)
FAMILY_BY_KEY = {family.key: family for family in FAMILIES}


def get_family(key: str | None) -> Family:
    """The family a row or request names; rows from before families are tabular."""

    return FAMILY_BY_KEY.get(str(key or TABULAR.key), TABULAR)


def family_of_task(task: str) -> Family | None:
    for family in FAMILIES:
        if task in family.tasks:
            return family
    return None


def all_tasks() -> tuple[str, ...]:
    return tuple(dict.fromkeys(task for family in FAMILIES for task in family.tasks))


__all__ = [
    "FAMILIES",
    "FORECASTING_FAMILY",
    "FAMILY_BY_KEY",
    "Family",
    "SpecField",
    "SpecInvalid",
    "TABULAR",
    "all_tasks",
    "family_of_task",
    "get_family",
]
