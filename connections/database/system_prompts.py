from datetime import datetime

import sqlalchemy
from sqlalchemy import DateTime as SQLADateTime
from sqlalchemy import Integer, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from connections.database.base import Base
from connections.database.utils import session_manager_decorator
from src.system_prompts import ALL_DEFAULT_SYSTEM_PROMPT_ROLE


class SystemPrompts(Base):
    """ORM model for system prompts."""

    __tablename__ = "system_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    language: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    llm_role_definition: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        SQLADateTime,
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
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
    def get_by_language(
        cls, language: str, *, session: Session | None = None
    ) -> "SystemPrompts | None":
        """
        Retrieve a SystemPrompts record by language.

        Parameters
        ----------
        language : str
            Language of the system prompt.
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        SystemPrompts | None
            The SystemPrompts record if found, otherwise None.
        """
        stmt = sqlalchemy.select(cls).where(cls.language == language)
        return session.execute(stmt).scalar_one_or_none()

    @classmethod
    @session_manager_decorator
    def get_all(
        cls,
        *,
        session: Session | None = None,
    ) -> list["SystemPrompts"]:
        """
        Retrieve all SystemPrompts records.

        Parameters
        ----------
        session : Session | None, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        list[SystemPrompts]
            List of SystemPrompts records, ordered by language.
        """
        stmt = sqlalchemy.select(cls).order_by(cls.language)
        return session.execute(stmt).scalars().all()

    @classmethod
    @session_manager_decorator
    def update(
        cls,
        record_id: int,
        *,
        session: Session | None = None,
        **updated_values: str | datetime,
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
        updated_values : str | datetime
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
        default_llm_role_definition = ALL_DEFAULT_SYSTEM_PROMPT_ROLE[language]
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
        for language, llm_role_definition in ALL_DEFAULT_SYSTEM_PROMPT_ROLE.items():
            new_prompt = cls(
                language=language,
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
