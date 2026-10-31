import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="doubtloop-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/t.db"
os.environ["CHROMA_PERSIST_DIRECTORY"] = f"{_tmp}/chroma"
os.environ["UPLOAD_DIRECTORY"] = f"{_tmp}/uploads"
os.environ["GEMINI_API_KEY"] = ""
