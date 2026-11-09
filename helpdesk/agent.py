"""Parts 2 and 3 - model + tools loop with conversation memory and user memory.

Graph:
    START -> load_user_memory -> agent --(tool calls, rounds < limit)--> tools -> agent ...
                                   |--(no tool calls)------------------------------> END
                                   '--(tool calls, rounds >= limit)--> limit_reached -> END

* The MODEL (in node `agent`) only REQUESTS tools by returning an AIMessage with tool_calls.
* The PROGRAM (node `tools`) actually runs them, then the results go back to the model.
* The loop limit is enforced by the conditional edge after `agent` (see route_after_agent).
* Conversation memory: LangGraph checkpointer, keyed by thread_id.
* User memory: UserMemory (SQLite), keyed by user_id. user_id and the status profile are
  supplied by the application in config["configurable"]; the model can never pick them.
"""
import json
import os
import sqlite3
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from . import tools as core
from .common import storage_dir
from .fake_model import FAKE_MODEL_NAME, ScriptedHelpdeskModel
from .memory import UserMemory

MAX_TOOL_ROUNDS = 4


# ---------------------------------------------------------------- tools shown to the model
def _ctx(config: RunnableConfig) -> dict:
    return (config or {}).get("configurable", {})


@tool("find_instructions")
def find_instructions_tool(topic: str) -> str:
    """Look up the local helpdesk instructions for a topic: 'wifi' or 'password'."""
    return json.dumps(core.find_instructions(topic))


@tool("check_service_status")
def check_service_status_tool(service: str, config: RunnableConfig) -> str:
    """Check whether a service is operating, has a known outage, or its status is unknown.
    service is 'wifi' or 'account_recovery' (use account_recovery for password problems)."""
    return json.dumps(core.check_service_status(service, _ctx(config).get("status_profile", "normal")))


@tool("prepare_ticket")
def prepare_ticket_tool(problem: str, steps_tried: list[str], config: RunnableConfig,
                        category: Optional[str] = None, service_status: Optional[str] = None,
                        reference_ids: Optional[list[str]] = None) -> str:
    """Prepare a LOCAL ticket draft (nothing is sent). Only use problem and steps_tried that the
    user actually stated; if either is missing, ask the user instead of calling this tool.
    service_status is 'operational', 'outage', 'unknown', or omitted if not checked."""
    c = _ctx(config)
    return json.dumps(core.prepare_ticket(
        problem, steps_tried, category, service_status, user_id=c.get("user_id"),
        thread_id=c.get("thread_id"), status_profile=c.get("status_profile"), reference_ids=reference_ids))


@tool("save_user_preference")
def save_user_preference_tool(key: str, value: str, config: RunnableConfig) -> str:
    """Save a preference the user asked you to remember. Only key 'reply_language' is supported
    (for example value 'Kazakh'). Never save passwords, keys or recovery codes."""
    c = _ctx(config)
    if key not in core.ALLOWED_PREFERENCES:
        return json.dumps({"saved": False, "error": f"unsupported preference '{key}'"})
    memory: UserMemory = c["_memory"]
    memory.save(c["user_id"], key, value)
    return json.dumps({"saved": True, "key": key, "value": value})


TOOLS = [find_instructions_tool, check_service_status_tool, prepare_ticket_tool, save_user_preference_tool]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


# ---------------------------------------------------------------- state and graph
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]   # conversation memory (checkpointed per thread)
    user_memory: dict                         # loaded from the user store at the start of each turn
    tool_rounds: int                          # tool rounds used in the current turn
    limit_reached: bool


def build_system_prompt(user_memory: dict) -> str:
    memory_lines = "\n".join(f"- {k}: {v}" for k, v in user_memory.items()) or "(nothing saved)"
    return (
        "You are a university IT helpdesk assistant (practice version, fictional data). "
        "You help with Wi-Fi troubleshooting, password recovery guidance, service status lookup "
        "and preparing LOCAL ticket drafts. Use the tools; do not invent instructions, status or "
        "repair times. If the user asks for a conditional action (for example 'prepare a ticket if "
        "the service is operating'), check the status first and follow the result. If the status is "
        "unknown, do not claim the service is operating; ask what the user wants. Never create a "
        "ticket with missing problem details or steps: ask the user. Never request or store "
        "passwords, API keys or recovery codes. Reply in the user's saved reply language if set.\n"
        f"User memory:\n{memory_lines}"
    )


def build_app(model, memory: UserMemory, checkpointer, max_tool_rounds: int = MAX_TOOL_ROUNDS):
    bound = model.bind_tools(TOOLS)

    def load_user_memory(state: AgentState, config: RunnableConfig) -> dict:
        user_id = config["configurable"]["user_id"]
        return {"user_memory": memory.load(user_id), "tool_rounds": 0, "limit_reached": False}

    def agent(state: AgentState) -> dict:
        reply = bound.invoke([SystemMessage(content=build_system_prompt(state["user_memory"]))] + state["messages"])
        return {"messages": [reply]}

    def tools_node(state: AgentState, config: RunnableConfig) -> dict:
        last: AIMessage = state["messages"][-1]
        cfg = {**config, "configurable": {**config["configurable"], "_memory": memory}}
        results = []
        for call in last.tool_calls:
            try:
                out = TOOLS_BY_NAME[call["name"]].invoke(call["args"], cfg)
            except Exception as exc:  # a bad tool call must not crash the loop
                out = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            results.append(ToolMessage(content=out, name=call["name"], tool_call_id=call["id"]))
        return {"messages": results, "tool_rounds": state["tool_rounds"] + 1}

    def limit_reached(state: AgentState) -> dict:
        note = ("I stopped because I reached the limit of tool steps for one message. "
                "Please rephrase or ask for one thing at a time.")
        return {"messages": [AIMessage(content=note)], "limit_reached": True}

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END                                  # the model answered
        if state["tool_rounds"] >= max_tool_rounds:
            return "limit_reached"                      # LOOP LIMIT enforced here
        return "tools"

    g = StateGraph(AgentState)
    g.add_node("load_user_memory", load_user_memory)
    g.add_node("agent", agent)
    g.add_node("tools", tools_node)
    g.add_node("limit_reached", limit_reached)
    g.add_edge(START, "load_user_memory")
    g.add_edge("load_user_memory", "agent")
    g.add_conditional_edges("agent", route_after_agent, ["tools", "limit_reached", END])
    g.add_edge("tools", "agent")
    g.add_edge("limit_reached", END)
    return g.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------- wiring helpers
def get_model(kind: str = "auto"):
    """kind: 'fake' | 'real' | 'auto' (real if OPENAI_API_KEY and MODEL_NAME are set, else fake).
    Returns (model, description)."""
    have_key = bool(os.environ.get("OPENAI_API_KEY")) and bool(os.environ.get("MODEL_NAME"))
    if kind == "real" or (kind == "auto" and have_key):
        if not have_key:
            raise SystemExit("Set OPENAI_API_KEY and MODEL_NAME (see .env.example) to use the real model.")
        from langchain_openai import ChatOpenAI
        name = os.environ["MODEL_NAME"]
        return ChatOpenAI(model=name, reasoning_effort="none"), f"openai:{name}"
    return ScriptedHelpdeskModel(), FAKE_MODEL_NAME


def open_storage(directory=None):
    """Open (or create) the SQLite checkpointer and the user-memory store in the storage dir."""
    from pathlib import Path
    d = Path(directory) if directory else storage_dir()
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(d / "checkpoints.sqlite", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    return checkpointer, UserMemory(d / "user_memory.sqlite"), conn
