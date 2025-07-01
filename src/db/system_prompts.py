from typing import Any

import sqlalchemy
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from src.db.utils import Base, session_manager_decorator
from src.system_prompts import ALL_DEFAULT_SYSTEM_PROMPT_ROLES


class SystemPrompts(Base):
    """
    ORM model for system prompts, representing AI assistant role definitions
    with a unique (language, system_prompt_type) combination.
    """

    __tablename__ = "system_prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    system_prompt_type = Column(String(255))
    language = Column(String(10))
    llm_role_definition = Column(Text)
    updated_by = Column(String(255))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            "language", "system_prompt_type", name="_lang_sttype_uc"
        ),
    )

    @classmethod
    @session_manager_decorator
    def get_by_id(
        cls, record_id: int, *, session: Session | None = None
    ) -> "SystemPrompts | None":
        """
        Retrieve a SystemPrompts record by its ID.

        Parameters
        ----------
        record_id : int
            ID of the SystemPrompts record to retrieve.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        SystemPrompts | None
            The SystemPrompts record if found, otherwise None.
        """
        stmt = sqlalchemy.select(cls).where(cls.id == record_id)
        return session.execute(stmt).scalar_one_or_none()

    @classmethod
    @session_manager_decorator
    def get_by_language_and_system_prompt_type(
        cls, language: str, system_prompt_type: str, *, session: Session | None = None
    ) -> "SystemPrompts | None":
        """
        Retrieve a SystemPrompts record by language and system_prompt_type.

        Parameters
        ----------
        language : str
            Language of the system prompt.
        system_prompt_type : str
            Type of the system prompt.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        SystemPrompts | None
            The SystemPrompts record if found, otherwise None.
        """
        stmt = sqlalchemy.select(cls).where(
            (cls.language == language) & (cls.system_prompt_type == system_prompt_type)
        )
        return session.execute(stmt).scalar_one_or_none()

    @classmethod
    @session_manager_decorator
    def get_all(
        cls, *, session: Session | None = None, filter_by_language: str | None = None
    ) -> list["SystemPrompts"]:
        """
        Retrieve all SystemPrompts records, optionally filtered by language.

        Parameters
        ----------
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.
        filter_by_language : str | None, optional
            If provided, filter records by this language.

        Returns
        -------
        list[SystemPrompts]
            List of SystemPrompts records, ordered by system_prompt_type.
        """
        stmt = sqlalchemy.select(cls).order_by(cls.system_prompt_type)
        if filter_by_language:
            stmt = stmt.where(cls.language == filter_by_language)
        return session.execute(stmt).scalars().all()

    @classmethod
    @session_manager_decorator
    def update(
        cls, record_id: int, *, session: Session | None = None, **updated_values: Any
    ) -> None:
        """
        Update a SystemPrompts record with the given values.

        Parameters
        ----------
        record_id : int
            ID of the SystemPrompts record to update.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.
        updated_values : Any
            Key-value pairs of fields to update in the SystemPrompts record.
        """
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
        system_prompt_type = old_system_prompt.system_prompt_type
        default_llm_role_definition = ALL_DEFAULT_SYSTEM_PROMPT_ROLES[language][
            system_prompt_type
        ]
        cls.update(
            record_id,
            session=session,
            llm_role_definition=default_llm_role_definition,
            updated_by=updated_by,
        )

    @classmethod
    @session_manager_decorator
    def reset_all(cls, updated_by: str, *, session: Session | None = None) -> None:
        """
        Reset all system prompts to their default values.

        Parameters
        ----------
        updated_by : str
            Identifier of the user or process performing the reset.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.
        """
        session.query(cls).delete()
        for language, prompts in ALL_DEFAULT_SYSTEM_PROMPT_ROLES.items():
            for system_prompt_type, llm_role_definition in prompts.items():
                new_prompt = cls(
                    language=language,
                    system_prompt_type=system_prompt_type,
                    llm_role_definition=llm_role_definition,
                    updated_by=updated_by,
                )
                session.add(new_prompt)

    @classmethod
    @session_manager_decorator
    def get_languages(cls, *, session: Session | None = None) -> list[str]:
        """
        Retrieve all unique languages from the system prompts.

        Parameters
        ----------
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        list[str]
            A list of unique languages available in the system prompts.
        """
        stmt = sqlalchemy.select(cls.language).distinct()
        result = session.execute(stmt).scalars().all()
        return result

    @classmethod
    @session_manager_decorator
    def get_system_prompt_types(
        cls, language: str, *, session: Session | None = None
    ) -> list[str]:
        """
        Retrieve all system prompt types for a given language.

        Parameters
        ----------
        language : str
            Language for which to retrieve system prompt types.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        list[str]
            A list of system prompt types available for the specified language.
        """
        stmt = sqlalchemy.select(cls.system_prompt_type).where(cls.language == language)
        result = session.execute(stmt).scalars().all()
        return result
