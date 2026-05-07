import os
import sys
from pathlib import Path

# Make orchestrator package importable from tests/
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "orchestrator"))

# Provide minimal env so settings load cleanly under tests
os.environ.setdefault("AUDVOICE_JWT_SECRET", "x" * 32)
os.environ.setdefault("AUDVOICE_API_KEYS", "devkey:tenant-dev")
os.environ.setdefault("AZURE_SPEECH_KEY", "test")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
