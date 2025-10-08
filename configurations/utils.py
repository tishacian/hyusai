from pathlib import Path

import toml

from configurations.subconfigs.streamlit import StreamlitConfig


def create_streamlit_config_file():
    config = StreamlitConfig()

    config_dir = Path.home() / ".streamlit"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "config.toml"

    with config_path.open("w") as f:
        toml.dump(config.model_dump(), f)
