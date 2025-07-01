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
    timestamp = Column(DateTime, default=func.now(), onupdate=func.now())
    chat_data = Column(Text)  # JSON serialized messages
    model_name = Column(String(255))
    chunking_method = Column(String(255))
    index_type = Column(String(255))
    vector_store = Column(String(255))
    pipeline_type = Column(String(255))
    instruction_lang = Column(String(10))

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
        *,
        timestamp: DateTime = func.now(),
        session: Session | None = None,
    ) -> int:
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
        stmt = sqlalchemy.delete(cls).where(cls.id == chat_id)
        session.execute(stmt)

    @classmethod
    @session_manager_decorator
    def delete_all_chats(cls, *, session: Session | None = None) -> None:
        session.query(cls).delete()

    @classmethod
    @session_manager_decorator
    def get_all_chats(
        cls, *, session: Session | None = None
    ) -> list[tuple[int, datetime]]:
        stmt = sqlalchemy.select(cls.id, cls.timestamp).order_by(cls.timestamp.desc())
        return session.execute(stmt).all()
