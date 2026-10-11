from typing import Literal

from celery.states import FAILURE, PENDING, REVOKED, STARTED, SUCCESS

CELERY_STATUSES = {FAILURE, PENDING, REVOKED, STARTED, SUCCESS}
type CeleryStatuses = Literal["FAILURE", "PENDING", "REVOKED", "STARTED", "SUCCESS"]
type CeleryStatusesFinal = Literal["FAILURE", "REVOKED", "SUCCESS"]
