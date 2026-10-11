from celery.backends.database.models import TaskExtended
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column


class TaskExtra(TaskExtended):
    """For the extra extend result."""

    __tablename__ = "celery_taskmeta"
    __table_args__ = {"sqlite_autoincrement": True, "extend_existing": True}

    progress_message: Mapped[str] = mapped_column(String(150), default="")
    logs: Mapped[str] = mapped_column(default="")

    def to_dict(self):
        task_dict = super().to_dict()
        task_dict.update(
            {
                "progress_message": self.progress_message,
                "logs": self.logs,
            }
        )
        return task_dict
