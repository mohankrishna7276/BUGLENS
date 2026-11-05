"""Central configuration for BugLens AI.

The Groq API key is read from a local ".env" file (never hardcoded).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --- Groq -------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b"
).strip()
GROQ_TEMPERATURE = 0.2
GROQ_MAX_TOKENS = 2048
MAX_CODE_CHARS = 8000  # keeps prompts inside free-tier token limits

# --- RAG --------------------------------------------------------------------
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHROMA_DIR = BASE_DIR / "chroma_db"
COLLECTION_NAME = "programming_errors"
KNOWLEDGE_FILE = BASE_DIR / "knowledge_base" / "programming_errors.json"
TOP_K = 3

# --- App --------------------------------------------------------------------
APP_NAME = "BugLens AI"
APP_TAGLINE = "Generative AI-Based Intelligent Code Debugging and Error Explanation System"
REPORTS_DIR = BASE_DIR / "reports"
SUPPORTED_LANGUAGES = ["Python", "Java", "C", "JavaScript"]
FILE_EXTENSIONS = {
    "py": "Python", "java": "Java", "c": "C", "h": "C", "js": "JavaScript",
}
