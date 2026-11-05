
"""Central configuration for BugLens AI.

Supports:
1. Local development through .env
2. Streamlit Cloud through st.secrets
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load local environment variables
load_dotenv(BASE_DIR / ".env")


# --------------------------------------------------
# Configuration helper
# --------------------------------------------------

def get_config(key, default=None):
    """Read Streamlit Cloud secrets first, then local environment."""

    try:
        value = st.secrets.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass

    value = os.getenv(key)

    if value is not None and value.strip():
        return value.strip()

    return default


# --------------------------------------------------
# Groq Configuration
# --------------------------------------------------

GROQ_API_KEY = get_config("GROQ_API_KEY", "")

GROQ_MODEL = get_config(
    "GROQ_MODEL",
    "openai/gpt-oss-120b"
)

GROQ_TEMPERATURE = 0.2
GROQ_MAX_TOKENS = 2048

MAX_CODE_CHARS = 8000


# --------------------------------------------------
# RAG Configuration
# --------------------------------------------------

EMBEDDING_MODEL = "all-MiniLM-L6-v2"

CHROMA_DIR = BASE_DIR / "chroma_db"

COLLECTION_NAME = "programming_errors"

KNOWLEDGE_FILE = (
    BASE_DIR / "knowledge_base" / "programming_errors.json"
)

TOP_K = 3


# --------------------------------------------------
# Application Configuration
# --------------------------------------------------

APP_NAME = "BugLens AI"

APP_TAGLINE = (
    "Generative AI-Based Intelligent Code Debugging "
    "and Error Explanation System"
)

REPORTS_DIR = BASE_DIR / "reports"

SUPPORTED_LANGUAGES = [
    "Python",
    "Java",
    "C",
    "JavaScript"
]

FILE_EXTENSIONS = {
    "py": "Python",
    "java": "Java",
    "c": "C",
    "h": "C",
    "js": "JavaScript",
}
