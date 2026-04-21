"""Help content loader — parses help_content.yaml into HelpContentIndex."""
from app.services.help_content.loader import load_help_index, get_help_index

__all__ = ["load_help_index", "get_help_index"]
