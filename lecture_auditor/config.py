import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

class Config:
    # LLM API configuration
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8082/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "local-model")

    # Search configuration
    TOP_K = int(os.getenv("TOP_K", "5"))

    # Database configuration
    DB_PATH = os.getenv("DB_PATH", "data/app.db")
    DATA_DIR = os.getenv("DATA_DIR", "data")

    # Server configuration
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))

    # Request timeout for LLM API (seconds)
    LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30.0"))

# Create a singleton instance
config = Config()