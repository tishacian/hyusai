from typing import Any

import sqlalchemy
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from src.db.utils import Base, session_manager_decorator

DEFAULT_PROMPTS = {
    "en": {
        "factual": "You are an AI assistant specialized in providing precise and factual information.",
        "analytical": "You are an AI assistant specialized in detailed analysis.",
        "comparative": "You are an AI assistant specialized in comparative analysis.",
        "causal": "You are an AI assistant specialized in causal analysis.",
        "hypothetical": "You are an AI assistant specialized in hypothetical reasoning.",
        "naive": "You are an AI assistant specialized in providing precise and detailed information.",
    },
    "fr": {
        "factual": "Tu es un assistant IA spécialisé dans la fourniture d'informations précises et factuelles.",
        "analytical": "Tu es un assistant IA spécialisé dans l'analyse approfondie.",
        "comparative": "Tu es un assistant IA spécialisé dans l'analyse comparative.",
        "causal": "Tu es un assistant IA spécialisé dans l'analyse causale.",
        "hypothetical": "Tu es un assistant IA spécialisé dans le raisonnement hypothétique.",
        "naive": "Tu es un assistant IA spécialisé dans la fourniture d'informations précises et détaillées.",
    },
}


class SystemPrompts(Base):
    """
    ORM model for system prompts, representing AI assistant role definitions
    with a unique (language, reasoning_type) combination.
    """

    __tablename__ = "system_prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reasoning_type = Column(String(255))
    language = Column(String(10))
    llm_role_definition = Column(Text)
    updated_by = Column(String(255))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            "language", "reasoning_type", name="_lang_reasoning_uc"
        ),
    )

    @classmethod
    @session_manager_decorator
    def get_by_id(
        cls, record_id: int, *, session: Session | None = None
    ) -> "SystemPrompts | None":
        """Retrieve a SystemPrompts record by its ID."""
        stmt = sqlalchemy.select(cls).where(cls.id == record_id)
        return session.execute(stmt).scalar_one_or_none()

    @classmethod
    @session_manager_decorator
    def get_by_language_and_reasoning_type(
        cls, language: str, reasoning_type: str, *, session: Session | None = None
    ) -> "SystemPrompts | None":
        """Retrieve a SystemPrompts record by language and reasoning_type."""
        stmt = sqlalchemy.select(cls).where(
            (cls.language == language) & (cls.reasoning_type == reasoning_type)
        )
        return session.execute(stmt).scalar_one_or_none()

    @classmethod
    @session_manager_decorator
    def get_all(
        cls, *, session: Session | None = None, filter_by_language: str | None = None
    ) -> list["SystemPrompts"]:
        """Retrieve all SystemPrompts, optionally filtered by language."""
        stmt = sqlalchemy.select(cls).order_by(cls.reasoning_type)
        if filter_by_language:
            stmt = stmt.where(cls.language == filter_by_language)
        return session.execute(stmt).scalars().all()

    @classmethod
    @session_manager_decorator
    def update(
        cls, record_id: int, *, session: Session | None = None, **updated_values: Any
    ) -> None:
        """Update fields of a SystemPrompts record by its ID."""
        stmt = (
            sqlalchemy.update(cls).where(cls.id == record_id).values(**updated_values)
        )
        session.execute(stmt)

    @classmethod
    @session_manager_decorator
    def reset(
        cls, record_id: int, updated_by: str, *, session: Session | None = None
    ) -> None:
        """Reset the llm_role_definition of a record to its default value."""
        old_system_prompt = cls.get_by_id(record_id, session=session)
        language = old_system_prompt.language
        reasoning_type = old_system_prompt.reasoning_type
        default_llm_role_definition = DEFAULT_PROMPTS[language][reasoning_type]
        cls.update(
            record_id,
            session=session,
            llm_role_definition=default_llm_role_definition,
            updated_by=updated_by,
        )

    @classmethod
    @session_manager_decorator
    def reset_all(cls, updated_by: str, *, session: Session | None = None) -> None:
        """Reset all system prompts to their default definitions."""
        session.query(cls).delete()
        for language, prompts in DEFAULT_PROMPTS.items():
            for reasoning_type, llm_role_definition in prompts.items():
                new_prompt = cls(
                    language=language,
                    reasoning_type=reasoning_type,
                    llm_role_definition=llm_role_definition,
                    updated_by=updated_by,
                )
                session.add(new_prompt)

    @classmethod
    @session_manager_decorator
    def get_languages(cls, *, session: Session | None = None) -> list[str]:
        """Return all unique languages available in system_prompts."""
        stmt = sqlalchemy.select(cls.language).distinct()
        result = session.execute(stmt).scalars().all()
        return result

    @classmethod
    @session_manager_decorator
    def get_reasoning_types(
        cls, language: str, *, session: Session | None = None
    ) -> list[str]:
        """Return all reasoning types available for the given language."""
        stmt = sqlalchemy.select(cls.reasoning_type).where(cls.language == language)
        result = session.execute(stmt).scalars().all()
        return result
