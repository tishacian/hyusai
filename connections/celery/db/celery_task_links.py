from datetime import datetime
from enum import StrEnum
from typing import TypedDict

from sqlalchemy import DateTime as SQLADateTime
from sqlalchemy import Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from connections.celery.db.base import ResultModelBase
from connections.celery.db.celery_task_extra_model import TaskExtra
from connections.celery.db.utils import session_manager_decorator


class LinkType(StrEnum):
    """Enumeration of possible types of links between Celery tasks."""

    chain = "chain"
    group = "group"
    chord = "chord"
    link_error = "link_error"
    link = "link"  # plain link signature or others


class TaskNode(TypedDict):
    """A node in the task graph representing a Celery task and its children."""

    task_id: str
    task_name: str
    task_status: str
    called_with: str
    called_at: datetime
    subtree: list["TaskNode"]  # recursive


def _walk(node: TaskNode, lines: list[str]) -> None:
    """
    Recursively traverse a task graph node and append Graphviz DOT
    statements for the node and its children to the provided lines list.

    Parameters
    ----------
    node : TaskNode
        The current task node in the graph, containing its task ID,
        link type, timestamp, and list of child nodes.
    lines : list[str]
        A list of strings representing the lines of a DOT graph;
        this function appends the DOT statements for the current node
        and its edges to this list.
    """
    node_id = node["task_id"]
    # add node with label including task name and called_at timestamp
    label = f"{node['task_name']}\\n{node['task_status']}\\n{node['called_at']}"
    lines.append(f'    "{node_id}" [label="{label}"];')
    for child in node["subtree"]:
        child_id = child["task_id"]
        # add edge with called_with as edge label
        lines.append(
            f'    "{node_id}" -> "{child_id}" [label="{child["called_with"]}"];'
        )
        _walk(child, lines)


def convert_graph_to_dot(graph: TaskNode) -> str:
    """
    Convert a nested task graph into Graphviz DOT format.

    Parameters
    ----------
    graph : TaskNode
        Root of the task graph.

    Returns
    -------
    str
        DOT representation of the graph.
    """
    lines = ["digraph G {"]
    _walk(graph, lines)
    lines.append("}")
    return "\n".join(lines)


class CeleryTaskLinks(ResultModelBase):
    __tablename__ = "celery_task_links"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_task_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("celery_taskmeta.task_id", ondelete="CASCADE"),
        index=True,
    )
    child_task_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("celery_taskmeta.task_id", ondelete="CASCADE"),
        index=True,
    )
    called_with: Mapped[LinkType] = mapped_column(
        Enum(LinkType),
        nullable=False,
        doc="How this child was scheduled.",
    )
    called_at: Mapped[datetime] = mapped_column(
        SQLADateTime, server_default=func.now(), nullable=False
    )

    parent = relationship(
        "TaskExtra", foreign_keys=[parent_task_id], backref="children_links"
    )
    child = relationship(
        "TaskExtra", foreign_keys=[child_task_id], backref="parent_links"
    )

    @classmethod
    @session_manager_decorator
    def add_link(
        cls,
        parent_task_id: str,
        child_task_id: str,
        link_type: LinkType,
        *,
        session: Session = None,
    ) -> "CeleryTaskLinks":
        """Add a new task link to the database.

        Parameters
        ----------
        parent_task_id : str
            The ID of the parent task.
        child_task_id : str
            The ID of the child task.
        link_type : LinkType
            The type of link (e.g., chain, group, chord).
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        CeleryTaskLinks
            The created CeleryTaskLinks object.
        """
        link = cls(
            parent_task_id=parent_task_id,
            child_task_id=child_task_id,
            called_with=link_type,
        )
        session.add(link)
        return link

    @classmethod
    @session_manager_decorator
    def get_children(
        cls, parent_task_id: str, *, session: Session = None
    ) -> list["CeleryTaskLinks"]:
        """Get all child tasks of the given parent_task_id.

        Parameters
        ----------
        parent_task_id : str
            The task ID to find children for.
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        list[CeleryTaskLinks]
            A list of CeleryTaskLinks representing the children tasks.
        """
        return (
            session.query(cls)
            .filter(cls.parent_task_id == parent_task_id)
            .order_by(cls.called_at)
            .all()
        )

    @classmethod
    @session_manager_decorator
    def get_parents(
        cls, child_task_id: str, *, session: Session = None
    ) -> list["CeleryTaskLinks"]:
        """Get all parent tasks of the given child_task_id.

        Parameters
        ----------
        child_task_id : str
            The task ID to find parents for.
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        list[CeleryTaskLinks]
            A list of CeleryTaskLinks representing the parent tasks.
        """
        return (
            session.query(cls)
            .filter(cls.child_task_id == child_task_id)
            .order_by(cls.called_at)
            .all()
        )

    @classmethod
    @session_manager_decorator
    def get_root_task(cls, child_task_id: str, *, session: Session = None) -> str:
        """
        Recursively find the root task of the given child_task_id.
        The root task is the one with no parent.

        Parameters
        ----------
        child_task_id : str
            The task ID to find the root for.
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        str
            The task_id of the root task.
        """
        parents = (
            session.query(cls)
            .filter(cls.child_task_id == child_task_id)
            .order_by(cls.called_at)
            .all()
        )
        if not parents:
            return child_task_id
        # for single parent, straightforward
        # for multi parents, pick the first (oldest) parent as their grand-parent
        # would be the same (callback)
        return cls.get_root_task(parents[0].parent_task_id, session=session)

    @classmethod
    @session_manager_decorator
    def _build_subtree(
        cls, current_task_id: str, *, session: Session = None
    ) -> list[TaskNode]:
        children_links = (
            session.query(cls)
            .filter(cls.parent_task_id == current_task_id)
            .order_by(cls.called_at)
            .all()
        )
        subtree = []
        for link in children_links:
            task_name = getattr(link.child, "name", "name unknown")
            task_status = getattr(link.child, "status", "status unknown")
            subtree.append(
                {
                    "task_id": link.child_task_id,
                    "task_name": task_name,
                    "task_status": task_status,
                    "called_with": link.called_with.value,
                    "called_at": link.called_at,
                    "subtree": cls._build_subtree(link.child_task_id, session=session),
                }
            )
        return subtree

    @classmethod
    @session_manager_decorator
    def get_task_graph(cls, task_id: str, *, session: Session = None) -> TaskNode:
        """Get the whole task graph including the given task ID.

        Parameters
        ----------
        task_id : str
            The task ID to retrieve the graph for.
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        """
        root_task_id = cls.get_root_task(task_id, session=session)
        task_obj = session.get(TaskExtra, root_task_id)
        task_name = getattr(task_obj, "name", "name unknown")
        task_status = getattr(task_obj, "status", "status unknown")
        graph: TaskNode = {
            "task_id": root_task_id,
            "task_name": task_name,
            "task_status": task_status,
            "called_with": "root",
            "called_at": datetime.min,
            "subtree": cls._build_subtree(root_task_id, session=session),
        }
        return graph

    @classmethod
    @session_manager_decorator
    def get_dot_task_graph(cls, task_id: str, *, session: Session = None) -> str:
        """Get the task graph in DOT format including the given task ID.

        Parameters
        ----------
        task_id : str
            The task ID to retrieve the graph for.
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        str
            The task graph in DOT format.
        """
        graph = cls.get_task_graph(task_id, session=session)
        dot_graph = convert_graph_to_dot(graph)
        return dot_graph
