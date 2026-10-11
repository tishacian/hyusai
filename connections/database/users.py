from datetime import datetime

from sqlalchemy import DateTime as SQLADateTime
from sqlalchemy import Integer, String, func, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from connections.database.base import Base
from connections.database.utils import session_manager_decorator


class Users(Base):
    """ORM model for user table."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        SQLADateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        SQLADateTime,
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )
    email: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="user")

    chats = relationship("Chats", back_populates="user", cascade="all, delete-orphan")

    @classmethod
    @session_manager_decorator
    def get_all(cls, *, session: Session = None) -> list["Users"]:
        """Get all users from the database.

        Returns
        -------
        list[Users]
            A list of all users in the database.
        """
        return session.execute(select(cls)).scalars().all()

    @classmethod
    @session_manager_decorator
    def get_by_id(cls, user_id: int, *, session: Session = None) -> "Users | None":
        """Get a user by their ID.

        Parameters
        ----------
        user_id : int
            The ID of the user to retrieve.
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        Users | None
            The user object if found, otherwise None.
        """
        return session.execute(
            select(cls).where(cls.id == user_id)
        ).scalar_one_or_none()

    @classmethod
    @session_manager_decorator
    def get_by_email(cls, email: str, *, session: Session = None) -> "Users | None":
        """Get a user by their email.

        Parameters
        ----------
        email : str
            The email of the user to retrieve.
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        Users | None
            The user object if found, otherwise None.
        """
        return session.execute(
            select(cls).where(cls.email == email)
        ).scalar_one_or_none()

    @classmethod
    @session_manager_decorator
    def add_user(
        cls,
        email: str,
        password_hash: str,
        name: str,
        role: str = "user",
        *,
        session: Session = None,
    ) -> "Users":
        """Add a new user to the database.

        Parameters
        ----------
        email : str
            The email of the user.
        password_hash : str
            The hashed password of the user.
        name : str
            The name of the user.
        role : str, optional
            The role of the user, by default "user"
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.

        Returns
        -------
        Users
            The newly created user object.
        """
        new_user = cls(
            email=email,
            password_hash=password_hash,
            name=name,
            role=role,
        )
        session.add(new_user)
        return new_user

    @classmethod
    @session_manager_decorator
    def update_password(
        cls, user_id: int, password_hash: str, *, session: Session = None
    ) -> None:
        """Update the password for a user.

        Parameters
        ----------
        user_id : int
            The ID of the user whose password is to be updated.
        password_hash : str
            The new hashed password for the user.
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.
        """
        session.execute(update(cls).where(cls.id == user_id).values(password_hash))

    @classmethod
    @session_manager_decorator
    def update_profile(
        cls,
        user_id: int,
        *,
        name: str | None = None,
        role: str | None = None,
        session: Session = None,
    ) -> None:
        """Update the profile of a user.

        Parameters
        ----------
        user_id : int
            The ID of the user whose profile is to be updated.
        name : str | None, optional
            The new name for the user, by default None.
            If None, the name will not be updated.
        role : str | None, optional
            The new role for the user, by default None.
            If None, the role will not be updated.
        session : Session, optional
            Automatically set by the context manager, by default None.
            Should not be set manually.
        """
        updates = {}
        if name is not None:
            updates["name"] = name
        if role is not None:
            updates["role"] = role

        if updates:
            session.execute(update(cls).where(cls.id == user_id).values(**updates))
