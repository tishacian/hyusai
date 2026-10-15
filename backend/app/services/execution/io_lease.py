"""Maintain a native lease while the parent performs bounded blocking I/O.

The heartbeat owns short, independent sessions and never touches the caller's
ORM transaction. Loss stops publication after the blocking call returns; it
does not pretend a thread can preempt a blocked SDK or release its resources.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Event, Thread

from sqlalchemy import text, update

from app.core.config import settings

from .admission import AdmissionError


@contextmanager
def maintain(model, identifier, token, *, status, session_factory=None, interval_s=None):
    if not token:
        yield
        return
    if session_factory is None:
        from app.db.base import SessionLocal

        session_factory = SessionLocal
    stopped, lost = Event(), Event()
    interval = interval_s or max(0.1, min(5, settings.execution_lease_s / 3))

    def renew():
        now = datetime.utcnow()
        try:
            with session_factory() as db:
                # A concurrent publication/reaper must never make a heartbeat
                # thread wait indefinitely while its caller waits to join it.
                if db.bind.dialect.name == "postgresql":
                    db.execute(text("SET LOCAL lock_timeout = '2s'"))
                    db.execute(text("SET LOCAL statement_timeout = '3s'"))
                deadline = db.query(model.deadline_at).filter_by(id=identifier).scalar()
                if deadline is None:
                    lost.set()
                    return
                result = db.execute(
                    update(model)
                    .where(
                        model.id == identifier,
                        model.lease_token == token,
                        model.status == status,
                        model.cancel_requested.is_(False),
                        model.lease_expires_at > now,
                        model.deadline_at > now,
                    )
                    .values(
                        lease_expires_at=min(
                            deadline, now + timedelta(seconds=settings.execution_lease_s)
                        )
                    )
                )
                db.commit()
                if result.rowcount != 1:
                    lost.set()
        except Exception:
            # No exception text from storage/DB credentials enters evidence.
            lost.set()

    def heartbeat():
        while not stopped.wait(interval) and not lost.is_set():
            renew()

    renew()
    if lost.is_set():
        raise AdmissionError("EXECUTION_LEASE_LOST")
    thread = Thread(target=heartbeat, name="execution-io-lease", daemon=True)
    thread.start()
    try:
        yield
        if lost.is_set():
            raise AdmissionError("EXECUTION_LEASE_LOST")
        renew()
        if lost.is_set():
            raise AdmissionError("EXECUTION_LEASE_LOST")
    finally:
        stopped.set()
        thread.join(timeout=4)
