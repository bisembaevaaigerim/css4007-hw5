"""A clearly labelled FAKE chat model used for tests and offline demonstrations.

It is NOT an LLM. It is a small deterministic script that imitates how a tool-calling model
behaves: it returns AIMessages that either request tools or give a final answer, and it
decides what to do from the messages it is shown (system prompt with user memory, the
conversation so far, and tool results). Its Kazakh output is a few canned sentences.

The real-model demonstration (Part 2) must be run separately with a real API key:
see README.md.
"""
import json
import re
import uuid
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

FAKE_MODEL_NAME = "scripted-fake-helpdesk-model (no LLM, no API)"

ASK_DETAILS = "What problem are you having, and what have you already tried?"
SCOPE = ("I can help with Wi-Fi troubleshooting, password recovery guidance, "
         "service status checks and local ticket drafts.")

KK = {
    "ack": "Жақсы, есте сақтадым: сіз қазақ тілінде жауап алғыңыз келеді.",
    "wifi_noted": "Wi-Fi мәселесін де жазып алдым.",
    "language": "Сіз қазақ тілінде жауап беруімді сұрадыңыз.",
    "scope": ("Мен Wi-Fi ақауын шешуге, құпия сөзді қалпына келтіру нұсқауларына, "
              "қызмет күйін тексеруге және жергілікті өтінім жобасын дайындауға көмектесемін."),
    "problem": "Сіз {topic} мәселесі туралы айттыңыз.",
    "steps": "Көрсеткен қадамдарыңыз: {steps}.",
    "no_problem": "Бұл әңгімеде мәселе әлі айтылған жоқ.",
}
KK_STEPS = {"Enabled Wi-Fi": "Wi-Fi қосылды", "Forgot the saved network": "сақталған желі ұмытылды",
            "Tried reconnecting": "қайта қосылу әрекеті жасалды"}

STEP_PATTERNS = [
    (r"enabled (?:wi-?fi|it)", "Enabled Wi-Fi"),
    (r"forgot the saved network", "Forgot the saved network"),
    (r"reconnect\w*", "Tried reconnecting"),
]


def _call(name: str, args: dict) -> dict:
    return {"name": name, "args": args, "id": "call_" + uuid.uuid4().hex[:10], "type": "tool_call"}


def _topic_of(text: str) -> Optional[str]:
    low = text.lower()
    if "wifi" in low or "wi-fi" in low:
        return "wifi"
    if "password" in low or "recovery" in low:
        return "password"
    return None


def _conversation_topic(texts: List[str]) -> Optional[str]:
    for t in reversed(texts):
        topic = _topic_of(t)
        if topic:
            return topic
    return None


def _steps_in(texts: List[str]) -> List[str]:
    """Steps the USER said they tried, in order of appearance. Nothing is invented."""
    found: List[str] = []
    for t in texts:
        low = t.lower()
        hits = []
        for pattern, label in STEP_PATTERNS:
            m = re.search(pattern, low)
            if m:
                hits.append((m.start(), label))
        for _, label in sorted(hits):
            if label not in found:
                found.append(label)
    return found


def _is_conditional(low: str) -> bool:
    return "if it is operating" in low or ("check" in low and ("down" in low or "status" in low) and "ticket" in low)


def _tool_results(messages: List[BaseMessage]) -> List[tuple]:
    out = []
    for m in messages:
        if isinstance(m, ToolMessage):
            try:
                out.append((m.name, json.loads(m.content)))
            except (TypeError, ValueError):
                out.append((m.name, {}))
    return out


def _service_for(topic: Optional[str]) -> str:
    return "account_recovery" if topic == "password" else "wifi"


def _label(topic: Optional[str]) -> str:
    return "account recovery" if topic == "password" else "Wi-Fi"


def _problem_text(topic: str, texts: List[str]) -> str:
    base = "Password recovery problem" if topic == "password" else "Wi-Fi connection still fails"
    if topic == "wifi" and any("campus-demo" in t.lower() for t in texts):
        base += " on the Campus-Demo network"
    return base


def decide(messages: List[BaseMessage]) -> AIMessage:
    system = next((m.content for m in messages if isinstance(m, SystemMessage)), "")
    lang_match = re.search(r"reply_language:\s*(\w+)", system)
    lang = lang_match.group(1).lower() if lang_match else None
    kk = lang == "kazakh"

    last_h = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    text = messages[last_h].content
    low = text.lower()
    prior = [m.content for m in messages[:last_h] if isinstance(m, HumanMessage)]
    all_human = prior + [text]
    turn = messages[last_h + 1:]
    history_results = _tool_results(messages)
    topic = _conversation_topic(all_human)
    steps = _steps_in(all_human)

    ticket_done = any(n == "prepare_ticket" and d.get("created") for n, d in history_results)
    ticket_pending = any("ticket" in p.lower() for p in prior) and not ticket_done

    # ---------------- continuing after a tool result ----------------
    if turn and isinstance(turn[-1], ToolMessage):
        name = turn[-1].name
        data = json.loads(turn[-1].content)
        if name == "save_user_preference":
            reply = KK["ack"] if str(data.get("value", "")).lower() == "kazakh" else \
                f"Noted. I will remember your {data.get('key')}: {data.get('value')}."
            if _topic_of(text) == "wifi":
                reply += " " + (KK["wifi_noted"] if kk or str(data.get("value", "")).lower() == "kazakh"
                                else "I also noted your Wi-Fi problem.")
            return AIMessage(content=reply)
        if name == "find_instructions":
            if not data.get("found"):
                return AIMessage(content=SCOPE)
            lines = "\n".join(f"{i}. {s}" for i, s in enumerate(data["steps"], 1))
            reply = f"[{data['instruction_id']}] {data['title']}\n{lines}"
            if steps:
                reply += f"\nYou said you already tried: {'; '.join(steps)}."
            return AIMessage(content=reply)
        if name == "check_service_status":
            label = _label(topic)
            status = data["status"]
            if _is_conditional(low) or ticket_pending:
                if status == "operational":
                    ids = [d["instruction_id"] for n, d in history_results if n == "find_instructions" and d.get("found")]
                    return AIMessage(content="", tool_calls=[_call("prepare_ticket", {
                        "problem": _problem_text(topic, all_human), "steps_tried": steps, "category": topic,
                        "service_status": "operational", "reference_ids": ids})])
                if status == "outage":
                    return AIMessage(content=(
                        f"The demo status source reports an outage for {label}. Your request said to prepare a ticket "
                        "if the service was operating, so I have not prepared that ticket. "
                        "The data does not give a repair time."))
                return AIMessage(content=(
                    f"I could not determine the {label} status. I cannot confirm that it is operating. "
                    "Would you like a ticket draft explaining that the status could not be checked?"))
            if status == "operational":
                return AIMessage(content=f"The demo status source reports {label} is operating. {data['message']}")
            if status == "outage":
                return AIMessage(content=f"Yes, there is a known problem: the demo status source reports an outage for {label}. "
                                         "The data does not give a repair time.")
            return AIMessage(content=f"I could not determine the {label} status. {data['message']}")
        if name == "prepare_ticket":
            if not data.get("created"):
                return AIMessage(content=ASK_DETAILS)
            status = data["ticket"]["service_status"]
            status_part = (f"The demo status source reports {_label(topic)} is operating. "
                           if status == "operational" else
                           "The service status was not checked for this draft. ")
            return AIMessage(content=(f"{status_part}I prepared a local draft describing the problem and the steps "
                                      f"you already tried. Nothing has been sent. Draft file: {data['filename']}"))
        return AIMessage(content=SCOPE)

    # ---------------- first step of a new user message ----------------
    pref = re.search(r"prefer(?:red)?\s+replies\s+in\s+([A-Za-z]+)", text, re.I) or \
        re.search(r"reply\s+in\s+([A-Za-z]+)", text, re.I)
    if pref and "remember" in low:
        return AIMessage(content="", tool_calls=[_call("save_user_preference", {
            "key": "reply_language", "value": pref.group(1).title()})])

    if "have i told you" in low or "previous problem" in low:
        if lang or prior:
            parts = []
            if lang:
                parts.append(f"Yes, you asked for replies in {lang.title()}.")
            if prior and topic:
                parts.append(f"You also reported a {_label(topic)} problem in this conversation.")
            return AIMessage(content=" ".join(parts))
        return AIMessage(content=("No preference or previous problem has been recorded for you yet. "
                                  "Tell me your preferred reply language or describe your problem."))

    if "which language" in low or "what language" in low:
        if not lang:
            return AIMessage(content="No reply-language preference has been recorded for you yet.")
        reply = (KK["language"] + " " + KK["scope"]) if kk else \
            f"You asked me to reply in {lang.title()}. " + SCOPE
        return AIMessage(content=reply)

    if any(k in low for k in ("which problem", "which steps", "what did we discuss", "already try", "did i already")):
        prev = all_human[:-1]
        prev_topic = _conversation_topic(prev)
        prev_steps = _steps_in(prev)
        if not prev_topic:
            return AIMessage(content=KK["no_problem"] if kk else "No problem has been described in this conversation yet.")
        if kk:
            names = "Wi-Fi" if prev_topic == "wifi" else "құпия сөз"
            msg = KK["problem"].format(topic=names)
            if prev_steps:
                msg += " " + KK["steps"].format(steps="; ".join(KK_STEPS.get(s, s) for s in prev_steps))
            return AIMessage(content=msg)
        msg = f"You reported a {_label(prev_topic)} problem."
        if prev_steps:
            msg += f" Steps you said you tried: {'; '.join(prev_steps)}."
        else:
            msg += " You have not said which steps you tried."
        return AIMessage(content=msg)

    wants_ticket = "ticket" in low and any(w in low for w in ("prepare", "create", "draft", "make", "open"))
    if wants_ticket or ticket_pending:
        if _is_conditional(low):
            if not topic:
                return AIMessage(content=ASK_DETAILS)
            return AIMessage(content="", tool_calls=[_call("check_service_status", {"service": _service_for(topic)})])
        if not topic or not steps:
            return AIMessage(content=ASK_DETAILS)
        return AIMessage(content="", tool_calls=[_call("prepare_ticket", {
            "problem": _problem_text(topic, all_human), "steps_tried": steps, "category": topic,
            "service_status": None, "reference_ids": []})])

    if "check" in low and any(w in low for w in ("status", "down", "known problem", "outage")):
        return AIMessage(content="", tool_calls=[_call("check_service_status", {"service": _service_for(topic)})])

    if _topic_of(text) or "steps" in low or "instructions" in low:
        return AIMessage(content="", tool_calls=[_call("find_instructions", {"topic": topic or "wifi"})])

    return AIMessage(content=SCOPE)


class ScriptedHelpdeskModel(BaseChatModel):
    """Deterministic stand-in for a tool-calling chat model (for tests and offline runs)."""

    model_name: str = FAKE_MODEL_NAME

    @property
    def _llm_type(self) -> str:
        return "scripted-fake-helpdesk"

    def bind_tools(self, tools, **kwargs):  # the script already knows the tool names
        return self

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=decide(messages))])


class RunawayToolModel(BaseChatModel):
    """Always asks for another tool call. Used only to test the loop limit."""

    @property
    def _llm_type(self) -> str:
        return "runaway-fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = AIMessage(content="", tool_calls=[_call("find_instructions", {"topic": "wifi"})])
        return ChatResult(generations=[ChatGeneration(message=msg)])
