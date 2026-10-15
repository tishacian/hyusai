"""Opt-in transport qualification; only a disposable local broker is stopped.

Celery publishes real confirmed persistent messages, Kombu consumes them and
the real PostgreSQL ML claim protects a small transactional fixture effect.
This does not run an ML trainer or qualify a production worker image.
"""

import os
import subprocess
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from celery import Celery
from kombu import Connection, Exchange, Queue
from sqlalchemy.orm import sessionmaker

from app.models.execution_control import ExecutionDispatch
from app.models.tabular import MLModel
from app.services.execution import dispatch, ml_lifecycle
from app.tests.services.test_activity_observability_postgres import pg as pg
from app.workers.celery_app import configure


@pytest.fixture
def broker():
    url = os.environ.get("ACTIVITY_RABBITMQ_URL")
    if not url:
        pytest.skip("ACTIVITY_RABBITMQ_URL required for disposable broker qualification")
    parsed = urlsplit(url)
    container = os.environ.get("ACTIVITY_RABBITMQ_CONTAINER")
    assert parsed.hostname == "127.0.0.1" and parsed.port == 15673
    assert container == "test_obs_rabbitmq"

    def control(action):
        subprocess.run(["docker", action, container], check=True, capture_output=True, timeout=30)
        if action == "start":
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    with Connection(url, connect_timeout=1) as connection:
                        connection.connect()
                    return
                except (OSError, ConnectionError):
                    time.sleep(0.1)
            pytest.fail("Disposable RabbitMQ did not become ready")

    control("start")
    try:
        yield url, control
    finally:
        control("start")  # Leave external fixture cleanup able to inspect it.


def test_confirm_outage_restart_and_redelivery_keep_native_claim_once(pg, broker):
    url, control = broker
    identifier = str(uuid4())
    queue_name = "execution_probe_" + uuid4().hex
    queue = Queue(queue_name, Exchange(queue_name, durable=True), queue_name, durable=True)
    app = configure(Celery("outbox-qualification", broker=url, backend=None))
    app.conf.update(
        task_queues=(queue,),
        broker_connection_timeout=1,
        broker_pool_limit=0,
        broker_transport_options={
            "confirm_publish": True,
            "connect_timeout": 1,
            "read_timeout": 1,
            "write_timeout": 1,
            "confirm_timeout": 1,
        },
    )
    assert app.conf.broker_transport_options["confirm_publish"] is True
    with Connection(url) as connection:
        queue(connection).declare()
    factory = sessionmaker(pg)
    with factory() as db:
        native = MLModel(
            id=identifier,
            workspace_id="pg-activity-ws",
            name="Transport fixture",
            slug=identifier,
            task="classification",
            target="label",
            algo="logistic_regression",
        )
        db.add(native)
        intent = dispatch.stage(
            db, "ml_training", native, deadline_at=datetime.utcnow() + timedelta(minutes=5)
        )
        intent.task_queue = queue_name
        task_id = intent.task_id
        db.commit()

    try:
        control("stop")
        started = time.monotonic()
        assert dispatch.publish_due(factory, publisher=app.send_task, limit=1) == 0
        assert time.monotonic() - started < 5
        with factory() as db:
            intent = db.query(ExecutionDispatch).one()
            assert intent.state == "pending" and intent.attempts == 1
            assert intent.error_code == "EXECUTION_BROKER_UNAVAILABLE"
            assert db.get(MLModel, identifier).status == "pending"
            intent.available_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        control("start")

        class PublisherExitAfterConfirm(BaseException):
            pass

        def exit_after_confirm(*args, **kwargs):
            app.send_task(*args, **kwargs)
            # Deterministic crash boundary: broker confirmed, DB not acknowledged.
            raise PublisherExitAfterConfirm()

        with pytest.raises(PublisherExitAfterConfirm):
            dispatch.publish_due(factory, publisher=exit_after_confirm, limit=1)
        with factory() as db:
            intent = db.query(ExecutionDispatch).one()
            assert intent.state == "leased" and intent.attempts == 2
            intent.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()

        # Confirmed durable message must survive an actual broker restart.
        control("stop")
        control("start")
        assert dispatch.publish_due(factory, publisher=app.send_task, limit=1) == 1
        with factory() as db:
            intent = db.query(ExecutionDispatch).one()
            assert intent.state == "published" and intent.attempts == 3
            assert intent.task_id == task_id

        claims, redelivered = [], []

        def consume(connection, *, ack):
            message = queue(connection).get(no_ack=False, accept=["json"])
            assert message is not None
            assert message.headers["id"] == task_id
            assert message.headers["task"] == "agentium.ml_train"
            assert message.properties["delivery_mode"] == 2
            assert message.payload[0] == [identifier]
            with factory() as db:
                native = db.get(MLModel, identifier)
                claimed = ml_lifecycle.start(db, native)
                if claimed:
                    native.status = "training"
                    native.metrics_json = {
                        "fixture_effects": (native.metrics_json or {}).get("fixture_effects", 0) + 1
                    }
                    db.commit()
                claims.append(claimed)
            redelivered.append(bool(message.delivery_info.get("redelivered")))
            if ack:
                message.ack()

        with Connection(url) as connection:
            consume(connection, ack=False)
            # Close after native commit, before broker ack: real AMQP redelivery.
        with Connection(url) as connection:
            consume(connection, ack=True)
            consume(connection, ack=True)
            assert queue(connection).get(no_ack=False) is None
        assert claims == [True, False, False]
        assert redelivered.count(True) == 1
        with factory() as db:
            assert db.get(MLModel, identifier).metrics_json == {"fixture_effects": 1}
    finally:
        control("start")
        with Connection(url) as connection:
            queue(connection).delete()
        app.close()
