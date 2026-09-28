"""Test isolation: point the app at a throwaway database and vector store.

Runs before any test module imports ``app``, so the settings below win over
``.env`` (python-dotenv never overrides variables that are already set).
Tests therefore never touch local dev data, never call a paid LLM API, and
behave the same on a fresh clone / CI runner as on a developer machine.
"""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="support_bot_tests_")

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ["CHROMA_PERSIST_DIR"] = os.path.join(_tmp, "chroma")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"  # unreachable on purpose
