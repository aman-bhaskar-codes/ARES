from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("ARES_MODE", "demo")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./.data/openapi.sqlite3")

from ares.api.app import create_app  # noqa: E402
from ares.api.settings import Settings  # noqa: E402

out = Path("backend/openapi.json")
app = create_app(Settings(ares_mode="demo", database_url="sqlite+pysqlite:///./.data/openapi.sqlite3"))
out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(out)
