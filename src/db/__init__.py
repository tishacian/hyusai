from .utils import Base, get_engine
from .system_prompts import SystemPrompts


def init_db():
    # create tables
    Base.metadata.create_all(get_engine())
    # fill system prompts table
    if len(SystemPrompts.get_all()) == 0:
        SystemPrompts.reset_all(updated_by="system")