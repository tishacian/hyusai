"""Run the Secure Deposit SFTP gateway."""
from __future__ import annotations

import asyncio
import logging

from app.services.secure_deposit_sftp import run_sftp_server


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_sftp_server())


if __name__ == "__main__":
    main()
