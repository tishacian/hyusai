"""Migration script that removes the prefix of all VDBs.
To perform migration run:
python -m migrations.2025_06_25_MR010
"""

import os


def migrate():
    base_dir = "vector_store"
    prefixes = ("faiss_", "weaviate_", "chroma_")

    if not os.path.isdir("vector_store"):
        print("⚠️ Vector store not found (probably not initialized). Migration skipped.")

    for entry in os.listdir(base_dir):
        full_path = os.path.join(base_dir, entry)
        if os.path.isdir(full_path) and entry.startswith(prefixes):
            new_name = entry
            for prefix in prefixes:
                if new_name.startswith(prefix):
                    new_name = new_name[len(prefix) :]
                    break  # Remove only one prefix
            new_path = os.path.join(base_dir, new_name)
            os.rename(full_path, new_path)
            print(f"Renamed: {entry} -> {new_name}")

    print("✅ Migration completed.")


if __name__ == "__main__":
    migrate()
