from .base import Base
from .chats import Chats as Chats
from .collections import Collection as Collection
from .system_prompts import SystemPrompts
from .users import Users
from .utils import get_engine


def init_db():
    Base.metadata.create_all(get_engine())
    if len(SystemPrompts.get_all()) == 0:
        SystemPrompts.reset_all(updated_by="system")


def seed_dev_user():
    dev_username = "dev"
    if Users.get_by_email(dev_username) is None:
        # won't be used as authentication is skipped, but this is hashed of `password`
        password_hash = "$2b$12$b47wpLrzEt5q5LEjZtcHBO5zZ4Yx1rWPdA8EE71dY6Ad0J9kFIBay"
        Users.add_user(
            email=dev_username,
            password_hash=password_hash,
            name="Development User",
        )
