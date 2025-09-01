from configuration import get_standalone_interface_config

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
    if get_standalone_interface_config().skip_authentication:
        dev_username = "dev"
        dev_user = Users.get_by_email(dev_username)
        if dev_user is None:
            Users.add_user(
                email=dev_username,
                password="password",  # won't be used as authentication is skipped
                name="Development User",
            )
