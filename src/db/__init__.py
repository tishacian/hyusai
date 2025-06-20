
from src.db.utils import Base, get_engine
from src.db.system_prompts.model import SystemPrompts


def init_db():
    # create tables
    Base.metadata.create_all(get_engine())
    # fill system prompts table
    if len(SystemPrompts.get_all()) == 0:
        SystemPrompts.reset_all(updated_by="system")