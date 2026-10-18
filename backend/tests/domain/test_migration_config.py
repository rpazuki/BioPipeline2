"""Encoded credentials must survive Alembic's ConfigParser layer."""

from io import StringIO
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


@pytest.mark.parametrize("password", ["encoded%40password", "encoded%25password", "plain-password"])
def test_migrations_accept_encoded_credentials(monkeypatch, password):
    url = f"postgresql+psycopg://example:{password}@127.0.0.1:5432/example"
    monkeypatch.setenv("BP_DATABASE_URL", url)
    output = StringIO()
    config = Config(output_buffer=output)
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    command.upgrade(config, "head", sql=True)
    assert "CREATE TABLE users" in output.getvalue()
    # Both offline and online migration paths receive a single percent sign.
    assert config.get_main_option("sqlalchemy.url") == url
    assert config.get_section(config.config_ini_section)["sqlalchemy.url"] == url
