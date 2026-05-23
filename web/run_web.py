"""Werewolf Web — start the web server."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "game"))
sys.path.insert(0, str(ROOT))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("web.app:app", host="127.0.0.1", port=8080, reload=True)
