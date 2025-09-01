import json
from datetime import datetime
from typing import Literal, TypedDict

import sqlalchemy
from sqlalchemy import DateTime as SQLADateTime
from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from src.db.utils import Base, session_manager_decorator


class Metrics(TypedDict):
    fluency: float
    coherence: float
    relevance: float
    factuality: float
    correctness: float
    hhem: float
    Advance_HHEM: float
    latency: float


class HumanChat(TypedDict):
    role: Literal["human"]
    content: str
    avatar: str


class AIChat(TypedDict):
    role: Literal["ai"]
    content: str
    metrics: Metrics
    avatar: str


class Chats(Base):
    """
    ORM model for chat history.
    """

    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        SQLADateTime,
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )
    chat_data: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(255))
    chunking_method: Mapped[str | None] = mapped_column(String(255))
    index_type: Mapped[str | None] = mapped_column(String(255))
    vector_store: Mapped[str | None] = mapped_column(String(255))
    pipeline_type: Mapped[str | None] = mapped_column(String(255))
    instruction_lang: Mapped[str | None] = mapped_column(String(10))

    user = relationship("Users", back_populates="chats")

    @classmethod
    @session_manager_decorator
    def post_chat(
        cls,
        user_id: int,
        chat_history: list[HumanChat | AIChat],
        model_name: str | None,
        chunking_method: str | None,
        index_type: str | None,
        vector_store: str | None,
        pipeline_type: str | None,
        instruction_lang: str | None,
        *,
        timestamp: datetime | None = None,
        session: Session | None = None,
    ) -> int:
        """
        Save a chat history to the database.
        Parameters
        ----------
        user_id : int
            ID of the user who initiated the chat.
        chat_history : list[HumanChat | AIChat]
            List of chat messages, where each message is a dictionary.
        model_name : str | None
            Name of the model used for the chat.
        chunking_method : str | None
            Chunking method used for the chat.
        index_type : str | None
            Type of index used for the chat.
        vector_store : str | None
            Vector store used for the chat.
        pipeline_type : str | None
            Type of pipeline used for the chat.
        instruction_lang : str | None
            Language of the instructions used in the chat.
        timestamp : DateTime | None, optional
            Datetime when the chat was created, by default None.
            If None, the current time will be used automatically.
            Should be used for migration only.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        int
            The ID of the newly created chat entry.
        """
        for msg in chat_history:
            if "avatar" in msg and isinstance(msg["avatar"], str):
                msg["avatar"] = msg["avatar"].split(",")[-1]
        chat_json = json.dumps(chat_history)
        if timestamp is None:
            new_chat = cls(
                user_id=user_id,
                chat_data=chat_json,
                model_name=model_name,
                chunking_method=chunking_method,
                index_type=index_type,
                vector_store=vector_store,
                pipeline_type=pipeline_type,
                instruction_lang=instruction_lang,
            )
        else:
            new_chat = cls(
                user_id=user_id,
                timestamp=timestamp,
                chat_data=chat_json,
                model_name=model_name,
                chunking_method=chunking_method,
                index_type=index_type,
                vector_store=vector_store,
                pipeline_type=pipeline_type,
                instruction_lang=instruction_lang,
            )
        session.add(new_chat)
        session.flush()
        return new_chat.id

    @classmethod
    @session_manager_decorator
    def update_chat(
        cls,
        chat_id: int,
        chat_history: list[HumanChat | AIChat],
        model_name: str | None,
        chunking_method: str | None,
        index_type: str | None,
        vector_store: str | None,
        pipeline_type: str | None,
        instruction_lang: str | None,
        *,
        session: Session | None = None,
    ) -> None:
        """
        Update an existing chat entry in the database.
        Parameters
        ----------
        chat_id : int
            ID of the chat entry to update.
        chat_history : list[HumanChat | AIChat]
            List of chat messages, where each message is a dictionary.
        model_name : str | None
            Name of the model used for the chat.
        chunking_method : str | None
            Chunking method used for the chat.
        index_type : str | None
            Type of index used for the chat.
        vector_store : str | None
            Vector store used for the chat.
        pipeline_type : str | None
            Type of pipeline used for the chat.
        instruction_lang : str | None
            Language of the instructions used in the chat.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.
        """
        chat_json = json.dumps(chat_history)
        stmt = (
            sqlalchemy.update(cls)
            .where(cls.id == chat_id)
            .values(
                chat_data=chat_json,
                model_name=model_name,
                chunking_method=chunking_method,
                index_type=index_type,
                vector_store=vector_store,
                pipeline_type=pipeline_type,
                instruction_lang=instruction_lang,
            )
        )
        session.execute(stmt)

    @classmethod
    @session_manager_decorator
    def get_chat(
        cls, chat_id: int, *, session: Session | None = None
    ) -> tuple[
        list[HumanChat | AIChat],
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
    ]:
        """
        Retrieve a chat entry from the database by its ID.

        Parameters
        ----------
        chat_id : int
            ID of the chat to retrieve.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        tuple[list[HumanChat | AIChat], str | None, str | None, str | None, str | None, str | None, str | None]
            A tuple containing the chat history as a list of dictionaries,
            the model name, chunking method, index type, vector store,
            pipeline type, and instruction language. If the chat does not exist,
            the chat history will be an empty list and the other fields will be None.
        """
        stmt = sqlalchemy.select(cls).where(cls.id == chat_id)
        result = session.execute(stmt).scalar_one_or_none()

        if result:
            chat_history = json.loads(result.chat_data)
            for msg in chat_history:
                if (
                    "avatar" in msg
                    and msg["avatar"]
                    and not msg["avatar"].startswith("data:image/png;base64,")
                ):
                    msg["avatar"] = f"data:image/png;base64,{msg['avatar']}"
            return (
                chat_history,
                result.model_name,
                result.chunking_method,
                result.index_type,
                result.vector_store,
                result.pipeline_type,
                result.instruction_lang,
            )
        return [], None, None, None, None, None, None

    @classmethod
    @session_manager_decorator
    def delete_chat(cls, chat_id: int, *, session: Session | None = None) -> None:
        """
        Delete a chat entry from the database by its ID.

        Parameters
        ----------
        chat_id : int
            ID of the chat to delete.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.
        """
        stmt = sqlalchemy.delete(cls).where(cls.id == chat_id)
        session.execute(stmt)

    @classmethod
    @session_manager_decorator
    def delete_all_user_chats(
        cls, user_id: int, *, session: Session | None = None
    ) -> None:
        """
        Delete all chat entries for a specific user from the database.

        Parameters
        ----------
        user_id : int
            ID of the user whose chats should be deleted.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.
        """
        stmt = sqlalchemy.delete(cls).where(cls.user_id == user_id)
        session.execute(stmt)

    @classmethod
    @session_manager_decorator
    def get_all_user_chats(
        cls, user_id: int, *, session: Session | None = None
    ) -> list[tuple[int, datetime]]:
        """
        Retrieve all chat IDs and their timestamps for a specific user,
        ordered by timestamp in descending order.

        Parameters
        ----------
        user_id : int
            ID of the user whose chats should be retrieved.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        list[tuple[int, datetime]]
            A list of tuples, each containing the chat ID and its timestamp,
            ordered by timestamp in descending order.
        """
        stmt = (
            sqlalchemy.select(cls.id, cls.timestamp)
            .where(cls.user_id == user_id)
            .order_by(cls.timestamp.desc())
        )
        return session.execute(stmt).all()
