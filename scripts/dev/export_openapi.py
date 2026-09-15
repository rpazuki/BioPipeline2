#!/usr/bin/env python3
"""Write the OpenAPI document to contracts/openapi.json.

The committed file is the contract. Every non-browser consumer -- a generated
TypeScript client, a CLI, the MCP server if it ships -- is built from it, so a
route changing shape without the contract changing is a change nobody
downstream can see coming.

`--check` compares instead of writing, and is what CI runs.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/openapi.json"


def build() -> dict:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.api.main import create_app  # noqa: PLC0415
    from app.settings import load_settings  # noqa: PLC0415

    # A fixed, offline configuration: the document must depend only on the
    # code, or the committed contract would differ between machines.
    settings = load_settings(environment="test", base_path="")
    app = create_app(settings=settings, engine=_null_engine())
    return app.openapi()


def _null_engine():
    """An engine that is never connected to.

    Generating the schema touches no database, but create_app wants one, and
    building a real engine would make this fail on a machine without Postgres.
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    return create_engine("postgresql+psycopg://unused:unused@localhost/unused")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if the committed file is stale"
    )
    args = parser.parse_args()

    document = json.dumps(build(), indent=2, sort_keys=True) + "\n"

    if args.check:
        if not CONTRACT.is_file():
            print(
                f"{CONTRACT} does not exist; run this without --check", file=sys.stderr
            )
            return 1
        if CONTRACT.read_text() != document:
            print(
                "contracts/openapi.json is stale.\n"
                "The API changed without the contract being regenerated, so every\n"
                "consumer generated from it is now wrong. Run:\n"
                "    make openapi",
                file=sys.stderr,
            )
            return 1
        print("openapi: contract matches the API")
        return 0

    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT.write_text(document)
    print(f"openapi: wrote {CONTRACT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
