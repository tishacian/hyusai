"""Claims reader: supplies the record identity of its investigation action.

The active claims configuration already knows that its investigation is run
per claim and carries ``claim_id``. Registering that here gives the claims
case its attempt history without republishing the app or touching its
binding, release or Flow.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.ecommerce import claims
from app.services.experience.record_identity import register_record_identity_provider

CLAIMS_APP_SLUG = "reclamations"
INVESTIGATE_BINDING = "showcase.claims.investigate"
CLAIM_IDENTITY = {"namespace": "claim", "input_field": "claim_id"}


def claims_record_identity(workspace: Any, experience_slug: str, binding_key: str) -> Optional[dict]:
    if experience_slug != CLAIMS_APP_SLUG or binding_key != INVESTIGATE_BINDING or workspace is None:
        return None
    try:
        claims._config(workspace)  # active, configured claims reader only
    except ValueError:
        return None
    return dict(CLAIM_IDENTITY)


register_record_identity_provider(claims_record_identity)
