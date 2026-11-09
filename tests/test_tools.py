import json

from helpdesk.tools import check_service_status, find_instructions, prepare_ticket


def test_find_instructions_wifi_and_password():
    """Catches: wrong guide returned, or steps not read from helpdesk.json."""
    assert find_instructions("Wi-Fi")["instruction_id"] == "GUIDE-WIFI"
    assert find_instructions("PASSWORD")["instruction_id"] == "GUIDE-PASSWORD"
    assert find_instructions("Wi-Fi")["steps"][1].startswith("Select")


def test_find_instructions_unknown_topic():
    """Catches: inventing instructions for unsupported topics."""
    assert find_instructions("printer")["found"] is False


def test_status_differs_by_profile():
    """Catches: ignoring the selected snapshot (the same request must give different results)."""
    assert check_service_status("wifi", "normal")["status"] == "operational"
    assert check_service_status("wifi", "wifi_outage")["status"] == "outage"
    assert check_service_status("wifi", "status_unavailable")["status"] == "unknown"


def test_password_topic_uses_account_recovery_service():
    """Catches: checking Wi-Fi status for a password problem (S14)."""
    r = check_service_status("password", "recovery_outage")
    assert r["service"] == "account_recovery" and r["status"] == "outage"
    assert check_service_status("wifi", "recovery_outage")["status"] == "operational"


def test_status_unknown_profile_or_service_is_unknown_not_operational():
    """Catches: treating missing data as 'operational'."""
    assert check_service_status("toaster", "normal")["status"] == "unknown"
    assert check_service_status("wifi", "no_such_profile")["status"] == "unknown"


def test_prepare_ticket_writes_local_draft(tmp_path):
    """Catches: ticket not saved, wrong fields, ticket marked as sent."""
    r = prepare_ticket("Wi-Fi fails", ["Enabled Wi-Fi"], "wifi", "operational",
                       user_id="demo-user-a", thread_id="t1", status_profile="normal", reference_ids=["GUIDE-WIFI"])
    assert r["created"] and r["sent"] is False
    saved = json.loads((tmp_path / "tickets" / r["filename"]).read_text())
    assert saved["status"] == "draft" and saved["steps_tried"] == ["Enabled Wi-Fi"]
    assert saved["user_id"] == "demo-user-a" and saved["reference_ids"] == ["GUIDE-WIFI"]


def test_prepare_ticket_refuses_missing_details(tmp_path):
    """Catches: filling missing details with invented facts."""
    r = prepare_ticket("", [])
    assert r["created"] is False and set(r["missing"]) == {"problem description", "steps already tried"}
    assert not (tmp_path / "tickets").exists() or not list((tmp_path / "tickets").iterdir())


def test_ticket_not_checked_status_is_explicit(tmp_path):
    """Catches: claiming a status when the service was never checked."""
    r = prepare_ticket("Wi-Fi fails", ["Tried reconnecting"])
    assert r["ticket"]["service_status"] == "not checked"
