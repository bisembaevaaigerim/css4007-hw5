"""The reusable tools. Plain Python functions: they work without any agent or model.

The agent (agent.py) wraps them so the MODEL only chooses the arguments shown here;
the application supplies user_id, thread_id and status profile (the model never does).
"""
import json
import uuid
from datetime import datetime, timezone

from .common import ROOT, load_json, ticket_dir

ALLOWED_PREFERENCES = {"reply_language"}


def _normalise_topic(text: str):
    """Map 'Wi-Fi', 'WIFI', 'password' ... to the topic key used in helpdesk.json."""
    aliases = load_json("helpdesk.json")["topic_aliases"]
    low = (text or "").lower()
    for topic, words in aliases.items():
        if topic == low or any(w in low for w in words):
            return topic
    return None


def find_instructions(topic: str) -> dict:
    """Look up Wi-Fi or password instructions in the local helpdesk data (retrieval)."""
    key = _normalise_topic(topic)
    data = load_json("helpdesk.json")
    if key is None:
        return {"found": False, "topic": topic, "supported_topics": sorted(data["instructions"])}
    item = data["instructions"][key]
    return {
        "found": True,
        "topic": key,
        "instruction_id": item["instruction_id"],
        "title": item["title"],
        "steps": item["steps"],
        "source": "data/helpdesk.json",
    }


def check_service_status(service: str, status_profile: str = "normal") -> dict:
    """Look up whether a service is operating, has a known outage, or is unknown.

    service: 'wifi' or 'account_recovery' (a 'password' topic is mapped to account_recovery).
    The snapshot (status_profile) is chosen by the application, not by the model.
    """
    topic_services = load_json("helpdesk.json")["topic_services"]
    low = (service or "").lower()
    service_key = topic_services.get(_normalise_topic(low) or "", low)
    if low in ("account_recovery", "account recovery", "recovery"):
        service_key = "account_recovery"
    profiles = load_json("service_status.json")["profiles"]
    if status_profile not in profiles:
        return {"service": service_key, "status": "unknown", "status_profile": status_profile,
                "message": f"Unknown status profile '{status_profile}'.", "source": "data/service_status.json"}
    entry = profiles[status_profile].get(service_key)
    if entry is None:
        return {"service": service_key, "status": "unknown", "status_profile": status_profile,
                "message": f"No status information exists for '{service}'.", "source": "data/service_status.json"}
    return {"service": service_key, "status": entry["status"], "message": entry["message"],
            "status_profile": status_profile, "source": "data/service_status.json"}


def prepare_ticket(problem: str, steps_tried: list, category: str = None, service_status: str = None,
                   user_id: str = None, thread_id: str = None, status_profile: str = None,
                   reference_ids: list = None) -> dict:
    """Prepare a LOCAL ticket draft. Nothing is sent anywhere.

    Refuses (returns an error, writes nothing) if the problem description or the steps
    already tried are missing - the ticket policy says missing details must be asked, not invented.
    """
    missing = []
    if not (problem or "").strip():
        missing.append("problem description")
    if not [s for s in (steps_tried or []) if str(s).strip()]:
        missing.append("steps already tried")
    if missing:
        return {"created": False, "error": "missing_information", "missing": missing}
    template = load_json("ticket_template.json")["ticket"]
    ticket = dict(template)
    ticket_id = "TCK-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    ticket.update({
        "ticket_id": ticket_id,
        "status": "draft",
        "user_id": user_id,
        "thread_id": thread_id,
        "category": category,
        "summary": problem.strip(),
        "steps_tried": [str(s).strip() for s in steps_tried if str(s).strip()],
        "service_status": service_status or "not checked",
        "status_profile": status_profile,
        "reference_ids": list(reference_ids or []),
    })
    path = ticket_dir() / f"{ticket_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ticket, f, ensure_ascii=False, indent=2)
    try:
        shown_path = str(path.relative_to(ROOT))   # keep logs free of machine-specific paths
    except ValueError:
        shown_path = path.name
    return {"created": True, "ticket_id": ticket_id, "filename": path.name, "path": shown_path,
            "sent": False, "ticket": ticket}
