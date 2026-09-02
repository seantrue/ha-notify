
import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Isolate every test from the developer's real environment and .env files."""
    for var in ("HA_TOKEN", "HA_URL", "HA_NOTIFY_TARGET"):
        monkeypatch.delenv(var, raising=False)
    # cwd inside an empty tmp dir so find_dotenv() cannot walk into a real .env
    monkeypatch.chdir(tmp_path)
    return tmp_path
