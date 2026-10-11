import pathlib
import sys

import streamlit.web.cli as stcli

from configurations.utils import create_streamlit_config_file

if __name__ == "__main__":
    create_streamlit_config_file()

    app_path = pathlib.Path("src/standalone_interface/omnirag.py")
    sys.argv = ["streamlit", "run", str(app_path)]
    sys.exit(stcli.main())
