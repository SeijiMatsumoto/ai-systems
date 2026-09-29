"""Configure backend telemetry once, before framework instrumentation."""

import os

import logfire
from dotenv import load_dotenv


load_dotenv("backend/.env")

# Logfire uses a write token for OTLP export. A project API key with the
# Send telemetry permission can be used as that token as well.
_write_token = os.getenv("LOGFIRE_TOKEN") or os.getenv("LOGFIRE_API_KEY")
EXPORT_ENABLED = (
    os.getenv("LOGFIRE_SEND_TO_LOGFIRE", "").lower() != "false"
    and bool(_write_token)
)

logfire.configure(
    token=_write_token,
    send_to_logfire="if-token-present" if EXPORT_ENABLED else False,
)
logfire.instrument_pydantic_ai()
