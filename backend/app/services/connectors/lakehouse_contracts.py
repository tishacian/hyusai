"""Declarative lakehouse endpoint policy; signed locations are never configuration."""

from app.services.connectors.connections import ConnectionError
from app.services.connectors.tool_contracts import allowed_url


def validate_config(config):
    allowed_url(config, config.get("base_url", ""))
    origins = config.get("download_origins")
    if not isinstance(origins, list) or not origins:
        raise ConnectionError("CONNECTOR_DOWNLOAD_ORIGIN_REQUIRED")
    for entry in origins:
        allowed_url({"allowed_origins": origins}, entry)
    # A configured location cannot smuggle a SAS/presigned credential into JSON.
    if "?" in config["base_url"]:
        raise ConnectionError("CONNECTOR_URL_INVALID")
