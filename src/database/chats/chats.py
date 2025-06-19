import json
import sqlite3
from datetime import datetime


class ChatsDB:
    def __init__(self):
        self.conn = sqlite3.connect("chat_history.db", check_same_thread=False)
        self.c = self.conn.cursor()
        self.c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chats'"
        )
        if self.c.fetchone() is None:
            self.c.execute(
                """
                CREATE TABLE chats (
                    id INTEGER PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    chat_data TEXT,
                    model_name TEXT,
                    chunking_method TEXT,
                    index_type TEXT,
                    vector_store TEXT,
                    pipeline_type TEXT,
                    instruction_lang TEXT
                )
            """
            )
        else:
            columns_to_add = [
                ("model_name", "TEXT"),
                ("chunking_method", "TEXT"),
                ("index_type", "TEXT"),
                ("vector_store", "TEXT"),
                ("pipeline_type", "TEXT"),
                ("instruction_lang", "TEXT"),
            ]
            for column_name, column_type in columns_to_add:
                self.c.execute("PRAGMA table_info(chats)")
                existing_columns = [column[1] for column in self.c.fetchall()]
                if column_name not in existing_columns:
                    self.c.execute(
                        f"ALTER TABLE chats ADD COLUMN {column_name} {column_type}"
                    )

        self.conn.commit()

    def post_chat(
        self,
        chat_history,
        model_name,
        chunking_method,
        index_type,
        vector_store,
        pipeline_type,
        instruction_lang,
    ):
        chat_data = []
        for msg in chat_history:
            msg_copy = msg.copy()
            if "avatar" in msg_copy and isinstance(msg_copy["avatar"], str):
                msg_copy["avatar"] = msg_copy["avatar"].split(",")[-1]
            chat_data.append(msg_copy)

        chat_json = json.dumps(chat_data)
        current_time = datetime.now().isoformat()

        self.c.execute(
            """
            INSERT INTO chats 
            (chat_data, timestamp, model_name, chunking_method, index_type, vector_store, pipeline_type, instruction_lang) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_json,
                current_time,
                model_name,
                chunking_method,
                index_type,
                vector_store,
                pipeline_type,
                instruction_lang,
            ),
        )
        self.conn.commit()
        return self.c.lastrowid

    def update_chat(
        self,
        chat_id,
        chat_history,
        model_name,
        chunking_method,
        index_type,
        vector_store,
        pipeline_type,
        instruction_lang,
    ):
        self.c.execute(
            """
            UPDATE chats 
            SET chat_data = ?, model_name = ?, chunking_method = ?, index_type = ?, vector_store = ?, pipeline_type = ?, instruction_lang = ?
            WHERE id = ?
            """,
            (
                chat_history,
                model_name,
                chunking_method,
                index_type,
                vector_store,
                pipeline_type,
                instruction_lang,
                chat_id,
            ),
        )
        self.conn.commit()

    def get_chat(self, chat_id):
        self.c.execute(
            """
            SELECT chat_data, model_name, chunking_method, index_type, vector_store, pipeline_type, instruction_lang 
            FROM chats WHERE id = ?
        """,
            (chat_id,),
        )
        result = self.c.fetchone()
        if result:
            chat_history = json.loads(result[0])
            for msg in chat_history:
                if "avatar" in msg and msg["avatar"]:
                    if not msg["avatar"].startswith("data:image/png;base64,"):
                        msg["avatar"] = f"data:image/png;base64,{msg['avatar']}"
            return (
                chat_history,
                result[1],
                result[2],
                result[3],
                result[4],
                result[5],
                result[6],
            )
        return [], None, None, None, None, None, None

    def delete_chat(self, chat_id):
        self.c.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self.conn.commit()

    def delete_all_chats(self):
        self.c.execute("DELETE FROM chats")
        self.conn.commit()

    def get_all_chats(self):
        try:
            self.c.execute("SELECT id, timestamp FROM chats ORDER BY timestamp DESC")
            return self.c.fetchall()
        except sqlite3.OperationalError:
            self.c.execute("ALTER TABLE chats ADD COLUMN timestamp TEXT")
            self.conn.commit()
            current_time = datetime.now().isoformat()
            self.c.execute(
                "UPDATE chats SET timestamp = ? WHERE timestamp IS NULL",
                (current_time,),
            )
            self.conn.commit()
            self.c.execute("SELECT id, timestamp FROM chats ORDER BY timestamp DESC")
            return self.c.fetchall()
