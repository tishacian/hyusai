# to perform migration run:
# python -m src.db.migrations.2025_06_23_MR006_sqlite_to_sqlalchemy

from datetime import datetime
import json
import os
import sqlite3

from src.db.chats import Chats
from src.db.utils import Base, get_engine

# Path to the old SQLite database
OLD_DB_PATH = "chat_history.db"


def migrate_chats():
    if not os.path.exists(OLD_DB_PATH):
        print("❌ Old database not found. No migration performed.")
        return

    # create chats table if needed
    Base.metadata.create_all(get_engine())
    if len(Chats.get_all_chats()) > 0:
        print("✅ New database already contains data. Migration skipped.")
        return

    conn = sqlite3.connect(OLD_DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM chats ORDER BY id")
    rows = cursor.fetchall()

    columns = [col[0] for col in cursor.description]

    for row in rows:
        chat = dict(zip(columns, row))
        chat_history = json.loads(chat["chat_data"])

        Chats.post_chat(
            chat_history=chat_history,
            model_name=chat.get("model_name"),
            chunking_method=chat.get("chunking_method"),
            index_type=chat.get("index_type"),
            vector_store=chat.get("vector_store"),
            pipeline_type=chat.get("pipeline_type"),
            instruction_lang=chat.get("instruction_lang"),
            timestamp=datetime.fromisoformat(chat.get("timestamp")),
        )

    print("✅ Migration completed.")


if __name__ == "__main__":
    migrate_chats()
