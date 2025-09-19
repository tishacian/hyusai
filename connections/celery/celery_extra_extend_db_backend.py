from celery.backends.database import DatabaseBackend, session_cleanup
from sqlalchemy.orm.attributes import flag_modified

from connections.celery.celery_task_extra_model import TaskExtra


class ExtraDatabaseBackend(DatabaseBackend):
    task_cls = TaskExtra

    def _store_result(
        self, task_id, result, state, traceback=None, request=None, **kwargs
    ):
        """Store return value and state of an executed task."""
        session = self.ResultSession()
        with session_cleanup(session):
            task = session.query(self.task_cls).filter_by(task_id=task_id).one_or_none()
            if task is None:
                task = self.task_cls(task_id)
                task.task_id = task_id
                session.add(task)
                session.flush()

            self._update_result(
                task, result, state, traceback=traceback, request=request, **kwargs
            )
            session.commit()

    def _update_result(
        self, task, result, state, traceback=None, request=None, **kwargs
    ):
        meta = self._get_result_meta(
            result=result,
            state=state,
            traceback=traceback,
            request=request,
            format_date=False,
            encode=True,
            **kwargs,
        )

        # Exclude the primary key id and task_id columns
        # as we should not set it None
        columns = [
            column.name
            for column in self.task_cls.__table__.columns
            if column.name not in {"id", "task_id"}
        ]

        # Iterate through the columns name of the table
        # to set the value from meta.
        # If the value is not present in meta, set None
        for column in columns:
            value = meta.get(column)

            if value is not None:
                setattr(task, column, value)
                flag_modified(task, column)

    def _get_result_meta(
        self,
        result,
        state,
        traceback,
        request,
        format_date=True,
        encode=False,
        **kwargs,
    ):
        meta = super()._get_result_meta(
            result, state, traceback, request, format_date, encode
        )
        if "progress_message" in kwargs:
            meta["progress_message"] = kwargs["progress_message"]
        if "logs" in kwargs:
            meta["logs"] = kwargs["logs"]
        return meta
