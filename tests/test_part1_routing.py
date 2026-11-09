import pytest

from helpdesk.part1 import run_with_trace

CASES = [
    ("I cannot connect to Wi-Fi.", "wifi_help"),
    ("I forgot my PASSWORD.", "password_help"),
    ("My laptop screen is broken.", "other_help"),
    ("My Wi-Fi password does not work.", "wifi_help"),   # original graph: wifi rule wins
    ("my WIFI is slow", "wifi_help"),
]


@pytest.mark.parametrize("message,node", CASES)
def test_original_routes(message, node):
    """Catches: wrong rule order, case-sensitive matching, wrong node chosen."""
    trace = run_with_trace(message, "original")
    assert trace["nodes_visited"] == ["START", "read_request", node, "END"]


def test_state_fields_are_set_in_order():
    """Catches: category/reply set by the wrong node, or the original message being overwritten."""
    trace = run_with_trace("I forgot my PASSWORD.")
    first, second = trace["steps"]
    assert first["node"] == "read_request" and first["state_after"]["category"] == "password"
    assert "reply" not in first["state_after"]
    assert second["state_after"]["reply"].startswith("[GUIDE-PASSWORD]")
    assert second["state_after"]["message"] == "I forgot my PASSWORD."


def test_both_topics_go_to_clarify_in_changed_graph():
    """Catches: the new clarify_problem node not being wired into the graph."""
    trace = run_with_trace("My Wi-Fi password does not work.", "with_clarification")
    assert trace["nodes_visited"] == ["START", "read_request", "clarify_problem", "END"]
    assert "Wi-Fi" in trace["final_reply"] and "password" in trace["final_reply"]


def test_changed_graph_keeps_single_topic_routes():
    """Catches: the change breaking the simple routes."""
    assert "wifi_help" in run_with_trace("wifi?", "with_clarification")["nodes_visited"]
    assert "password_help" in run_with_trace("password?", "with_clarification")["nodes_visited"]
