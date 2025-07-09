from .chats import Chats  # required for tables creation
from .system_prompts import SystemPrompts
from .users import Users  # required for tables creation
from .utils import Base, get_engine


def init_db():
    # create tables
    Base.metadata.create_all(get_engine())
    # fill system prompts table
    if len(SystemPrompts.get_all()) == 0:
        SystemPrompts.reset_all(updated_by="system")
