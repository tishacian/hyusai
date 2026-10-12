"""Historical import path of the HANA demo rows.

``app.seeds.hana_demo_rows`` is the source (ADR 0003). This module keeps the
previous path working for the seed script and the in-memory fallback.
"""

from app.seeds.hana_demo_rows import (  # noqa: F401
    EQUIPMENT_ROWS,
    ORDER_ROWS,
    PART_ROWS,
    TABLE_EQUIPMENT,
    TABLE_ORDERS,
    TABLE_PARTS,
)
