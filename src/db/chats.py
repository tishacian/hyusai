import json
from datetime import datetime
from typing import Literal, TypedDict

import sqlalchemy
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

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

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    chat_data = Column(Text, nullable=False)  # JSON serialized messages
    model_name = Column(String(255), nullable=False)
    chunking_method = Column(String(255), nullable=False)
    index_type = Column(String(255), nullable=False)
    vector_store = Column(String(255), nullable=False)
    pipeline_type = Column(String(255), nullable=False)
    instruction_lang = Column(String(10), nullable=False)
    user_id = Column(Integer, nullable=False)

    @classmethod
    @session_manager_decorator
    def post_chat(
        cls,
        chat_history: list[HumanChat | AIChat],
        model_name: str,
        chunking_method: str,
        index_type: str,
        vector_store: str,
        pipeline_type: str,
        instruction_lang: str,
        user_id: int,
        *,
        timestamp: DateTime = func.now(),
        session: Session | None = None,
    ) -> int:
        """
        Save a chat history to the database.
        Parameters
        ----------
        chat_history : list[HumanChat | AIChat]
            List of chat messages, where each message is a dictionary.
        model_name : str
            Name of the model used for the chat.
        chunking_method : str
            Chunking method used for the chat.
        index_type : str
            Type of index used for the chat.
        vector_store : str
            Vector store used for the chat.
        pipeline_type : str
            Type of pipeline used for the chat.
        instruction_lang : str
            Language of the instructions used in the chat.
        timestamp : DateTime, optional
            Datetime when the chat was created, by default func.now()
            Should be used for migration only.
        user_id : int
            ID of the user who initiated the chat.
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

        new_chat = cls(
            chat_data=chat_json,
            model_name=model_name,
            chunking_method=chunking_method,
            index_type=index_type,
            vector_store=vector_store,
            pipeline_type=pipeline_type,
            instruction_lang=instruction_lang,
            timestamp=timestamp,
            user_id=user_id,
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
        model_name: str,
        chunking_method: str,
        index_type: str,
        vector_store: str,
        pipeline_type: str,
        instruction_lang: str,
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
        model_name : str
            Name of the model used for the chat.
        chunking_method : str
            Chunking method used for the chat.
        index_type : str
            Type of index used for the chat.
        vector_store : str
            Vector store used for the chat.
        pipeline_type : str
            Type of pipeline used for the chat.
        instruction_lang : str
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
