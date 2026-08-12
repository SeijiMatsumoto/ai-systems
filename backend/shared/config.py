"""
Shared configurations and environment variables for all agent demos.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from parent directory if present
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

# Common paths
BASE_DIR = Path(__file__).resolve().parents[1]
DB_DIR = BASE_DIR / "shared" / "db"

# Ensure database directory exists
DB_DIR.mkdir(parents=True, exist_ok=True)

# API Keys (to be loaded from .env)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Add other database or vector store configs here as needed