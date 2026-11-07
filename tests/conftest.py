import os
import tempfile

# Settings are read at import time, so configure the offline gateway first.
_tmp = tempfile.mkdtemp(prefix="mollet-test-")
os.environ["MOLLET_MOCK"] = "1"
os.environ["MOLLET_DB"] = os.path.join(_tmp, "test.db")
os.environ.pop("OTARI_API_KEY", None)
os.environ.pop("MOLLET_MCP_SERVER_ID", None)
os.environ["MOLLET_GUARDRAILS"] = "prompt-injection"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client():
    from mollet import db
    from mollet.main import app

    if os.path.exists(os.environ["MOLLET_DB"]):
        os.remove(os.environ["MOLLET_DB"])
    db.init()
    from mollet import wallet

    wallet.clear_cache()
    with TestClient(app) as c:
        yield c
