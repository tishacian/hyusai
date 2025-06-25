"""Migration script that removes the prefix of all faiss/chroma VDBs.
To perform migration, run:
python -m migrations.2025_06_25_MR010
To perform downgrade migration, run:
python -m migrations.2025_06_25_MR010 down
"""

import os
import sys

BASE_DIR = "vector_store"
PREFIXES = ("faiss_", "chroma_")
FILE_BY_PREFIX = {"faiss_": "faiss.index", "chroma_": "chroma.sqlite3"}


def upgrade():
    if not os.path.isdir("vector_store"):
        print("⚠️ Vector store not found (probably not initialized). Migration skipped.")

    for entry in os.listdir(BASE_DIR):
        full_path = os.path.join(BASE_DIR, entry)
        if os.path.isdir(full_path) and entry.startswith(PREFIXES):
            new_name = entry
            for prefix in PREFIXES:
                if new_name.startswith(prefix):
                    new_name = new_name[len(prefix) :]
                    break  # Remove only one prefix
            new_path = os.path.join(BASE_DIR, new_name)
            os.rename(full_path, new_path)
            print(f"Renamed: {entry} -> {new_name}")

    print("✅ Migration completed.")


def downgrade():
    if not os.path.isdir("vector_store"):
        print(
            "⚠️ Vector store not found (probably not initialized). "
            "Downgrade migration skipped."
        )

    for entry in os.listdir(BASE_DIR):
        full_path = os.path.join(BASE_DIR, entry)
        if os.path.isdir(full_path):
            for prefix, expected_file in FILE_BY_PREFIX.items():
                expected_file_full_path = os.path.join(full_path, expected_file)
                if not entry.startswith(prefix) and os.path.isfile(
                    expected_file_full_path
                ):
                    new_name = prefix + entry
                    new_path = os.path.join(BASE_DIR, new_name)
                    os.rename(full_path, new_path)
                    print(f"Renamed: {entry} -> {new_name}")

    print("✅ Downgrade migration completed.")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "up"
    if arg == "up":
        upgrade()
    elif arg == "down":
        downgrade()
    else:
        print(f"Unknown argument: {arg}")
        print("Use up or down")
        sys.exit(1)
