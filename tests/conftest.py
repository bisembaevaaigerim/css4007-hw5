import pytest

from helpdesk.agent import build_app, open_storage
from helpdesk.fake_model import ScriptedHelpdeskModel


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Every test gets its own storage and ticket folders; nothing touches the real ones."""
    monkeypatch.setenv("HELPDESK_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("HELPDESK_TICKET_DIR", str(tmp_path / "tickets"))
    return tmp_path


@pytest.fixture
def make_app():
    """Open the app on the current storage dir. Call again to simulate a restart."""
    opened = []

    def _make(model=None, max_tool_rounds=4):
        checkpointer, memory, conn = open_storage()
        opened.append((memory, conn))
        return build_app(model or ScriptedHelpdeskModel(), memory, checkpointer, max_tool_rounds), memory

    yield _make
    for memory, conn in opened:
        memory.close()
        conn.close()
