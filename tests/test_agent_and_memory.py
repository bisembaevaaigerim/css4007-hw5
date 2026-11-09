import json
import subprocess
import sys

from helpdesk.common import ROOT
from helpdesk.fake_model import RunawayToolModel


def send(app, user, thread, text, profile="normal"):
    config = {"configurable": {"user_id": user, "thread_id": thread, "status_profile": profile}}
    state = app.invoke({"messages": [("user", text)]}, config)
    return state


def tools_called(state):
    return [m.name for m in state["messages"] if m.type == "tool"]


COND = ("I enabled Wi-Fi and forgot the saved network, but Campus-Demo still will not connect. "
        "Check whether Wi-Fi is down. If it is operating, prepare a ticket about this problem.")


def test_conditional_request_depends_on_status(make_app, tmp_path):
    """Catches: always making a ticket regardless of the status snapshot (S06/S07/S08)."""
    app, _ = make_app()
    ok = send(app, "demo-user-a", "t-ok", COND, "normal")
    assert tools_called(ok)[-2:] == ["check_service_status", "prepare_ticket"]
    assert "Nothing has been sent" in ok["messages"][-1].content
    down = send(app, "demo-user-a", "t-down", COND, "wifi_outage")
    assert tools_called(down) == ["check_service_status"] and "have not prepared" in down["messages"][-1].content
    unknown = send(app, "demo-user-a", "t-unk", COND, "status_unavailable")
    assert tools_called(unknown) == ["check_service_status"]
    assert "cannot confirm" in unknown["messages"][-1].content
    assert len(list((tmp_path / "tickets").iterdir())) == 1       # only the operating case made a ticket


def test_ticket_uses_only_stated_steps(make_app, tmp_path):
    """Catches: invented troubleshooting steps in the ticket."""
    app, _ = make_app()
    send(app, "demo-user-a", "t", COND)
    ticket = json.loads(next((tmp_path / "tickets").iterdir()).read_text())
    assert ticket["steps_tried"] == ["Enabled Wi-Fi", "Forgot the saved network"]


def test_missing_details_lead_to_question_then_ticket(make_app, tmp_path):
    """Catches: preparing a ticket before the problem and steps are known (S09)."""
    app, _ = make_app()
    first = send(app, "demo-user-a", "t9", "Prepare a support ticket.")
    assert tools_called(first) == [] and "already tried" in first["messages"][-1].content
    second = send(app, "demo-user-a", "t9", "The issue is Wi-Fi. I enabled it and tried reconnecting, but it still fails.")
    assert tools_called(second) == ["prepare_ticket"]
    assert json.loads(next((tmp_path / "tickets").iterdir()).read_text())["service_status"] == "not checked"


def test_loop_limit_stops_a_runaway_model(make_app):
    """Catches: an endless model <-> tools loop."""
    app, _ = make_app(RunawayToolModel(), max_tool_rounds=3)
    state = send(app, "demo-user-a", "loop", "hello")
    assert state["limit_reached"] is True and state["tool_rounds"] == 3
    assert len(tools_called(state)) == 3


def test_conversation_memory_within_a_thread(make_app):
    """Catches: the model not receiving earlier messages (S10)."""
    app, _ = make_app()
    send(app, "demo-user-a", "t10", "I cannot connect to Wi-Fi. I enabled it and forgot the saved network, but reconnecting failed.")
    answer = send(app, "demo-user-a", "t10", "Which steps did I already try?")["messages"][-1].content
    assert "Enabled Wi-Fi" in answer and "Forgot the saved network" in answer


def test_conversation_and_preference_survive_restart(make_app):
    """Catches: memory kept only in RAM. 'Restart' = close everything and reopen the same storage."""
    app, memory = make_app()
    send(app, "demo-user-a", "restart-a", "Please remember that I prefer replies in Kazakh. My issue is Wi-Fi. I enabled it and tried reconnecting, but it still fails.")
    memory.close()
    app2, memory2 = make_app()
    assert memory2.load("demo-user-a") == {"reply_language": "Kazakh"}
    answer = send(app2, "demo-user-a", "restart-a", "Which problem and steps did we discuss?")["messages"][-1].content
    assert "Wi-Fi" in answer and "қосылды" in answer       # recalled from the checkpoint, in the saved language


def test_real_process_restart_via_cli(tmp_path):
    """Catches: anything that only works inside one Python process (uses two real processes)."""
    env_dir = str(tmp_path / "cli-storage")
    import os
    env = {**os.environ, "HELPDESK_STORAGE_DIR": env_dir, "HELPDESK_TICKET_DIR": str(tmp_path / "tk")}
    base = [sys.executable, "-m", "helpdesk.cli", "--user", "demo-user-a", "--thread", "p", "--model", "fake"]
    subprocess.run(base + ["--message", "My issue is Wi-Fi. I enabled it and tried reconnecting, but it still fails."],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    out = subprocess.run(base + ["--message", "Which problem and steps did we discuss?"],
                         cwd=ROOT, env=env, check=True, capture_output=True, text=True).stdout
    assert "Enabled Wi-Fi" in out and "Tried reconnecting" in out


def test_preference_shared_across_threads_of_same_user(make_app):
    """Catches: preference tied to one thread instead of the user (S12), or transcript replay."""
    app, _ = make_app()
    send(app, "demo-user-a", "a1", "Please remember that I prefer replies in Kazakh. I have a Wi-Fi problem.")
    state = send(app, "demo-user-a", "a2", "Which language did I ask you to use? What can you help with?")
    assert state["user_memory"] == {"reply_language": "Kazakh"}
    assert "қазақ" in state["messages"][-1].content
    assert len(state["messages"]) == 2          # the old thread's messages were NOT replayed


def test_other_user_does_not_see_preference_or_history(make_app):
    """Catches: shared memory between users (S13)."""
    app, _ = make_app()
    send(app, "demo-user-a", "isolation-a", "Please remember that I prefer replies in Kazakh. I have a Wi-Fi problem.")
    state = send(app, "demo-user-b", "isolation-b", "Have I told you a preferred language or a previous problem?")
    assert state["user_memory"] == {}
    assert "No preference or previous problem" in state["messages"][-1].content
    assert "Kazakh" not in state["messages"][-1].content


def test_same_thread_id_is_a_different_conversation_per_thread(make_app):
    """Catches: threads sharing history. A new thread starts empty even for the same user."""
    app, _ = make_app()
    send(app, "demo-user-a", "old", "My issue is Wi-Fi. I enabled it and tried reconnecting.")
    fresh = send(app, "demo-user-a", "new", "Which problem and steps did we discuss?")
    assert "No problem has been described" in fresh["messages"][-1].content


def test_password_outage_uses_account_recovery(make_app):
    """Catches: looking up Wi-Fi for a password question (S14)."""
    app, _ = make_app()
    state = send(app, "demo-user-a", "s14", "My password recovery page is unavailable. Check the service status. Is there a known problem?", "recovery_outage")
    result = json.loads(next(m for m in state["messages"] if m.type == "tool").content)
    assert result["service"] == "account_recovery" and result["status"] == "outage"
    assert "repair time" in state["messages"][-1].content
