"""Write the API's OpenAPI schema to a file (the contract the frontend's types are generated from).

    uv run python -m sia.scripts.export_openapi frontend/src/lib/api/openapi.json

Builds the app with placeholder settings: no database or `.env` is needed, so CI can run it.
"""

import json
import sys
from pathlib import Path

from pydantic import SecretStr

from sia.core.config import Settings
from sia.main import create_app


def export(path: Path) -> None:
    settings = Settings(
        _env_file=None,
        SIA_ENV="development",
        POSTGRES_USER="placeholder",
        POSTGRES_PASSWORD=SecretStr("placeholder"),  # never used to connect
        SIA_APP_DB_PASSWORD=SecretStr("placeholder"),
    )
    schema = create_app(settings).openapi()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Wrote {path} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    export(Path(sys.argv[1] if len(sys.argv) > 1 else "frontend/src/lib/api/openapi.json"))
