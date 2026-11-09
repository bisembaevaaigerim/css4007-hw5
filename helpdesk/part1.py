"""Part 1 - a helpdesk graph with NO language model.

Original graph:
    START -> read_request -> (conditional edge) -> wifi_help | password_help | other_help -> END

With clarification (variant="with_clarification") there is one more branch:
    ... -> clarify_problem -> END      (when the message mentions both Wi-Fi and a password)

Run:  python -m helpdesk.part1 --message "I forgot my PASSWORD." [--variant with_clarification]
"""
import argparse
import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .common import load_json


class HelpState(TypedDict, total=False):
    message: str    # the user's original message (never changed)
    category: str   # set by read_request
    reply: str      # set by a help node


def _topics(message: str) -> set:
    """Which topics does the message mention? Case-insensitive."""
    aliases = load_json("helpdesk.json")["topic_aliases"]
    text = message.lower()
    return {topic for topic, words in aliases.items() if any(w in text for w in words)}


def _format_instructions(topic: str) -> str:
    item = load_json("helpdesk.json")["instructions"][topic]
    steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(item["steps"], 1))
    return f"[{item['instruction_id']}] {item['title']}\n{steps}"


def build_graph(variant: str = "original"):
    """Build and compile the Part 1 graph. variant: 'original' or 'with_clarification'."""
    if variant not in ("original", "with_clarification"):
        raise ValueError(f"unknown variant: {variant}")
    clarify = variant == "with_clarification"          # NEW: switch between old and new graph

    # --- nodes: each reads the state and returns an UPDATE (a dict of changed keys) ---
    def read_request(state: HelpState) -> dict:
        topics = _topics(state["message"])
        if clarify and {"wifi", "password"} <= topics:  # NEW: both topics -> special category
            return {"category": "both"}
        if "wifi" in topics:          # rule 1: wifi wins in the original graph
            return {"category": "wifi"}
        if "password" in topics:      # rule 2
            return {"category": "password"}
        return {"category": "other"}  # rule 3

    def wifi_help(state: HelpState) -> dict:
        return {"reply": _format_instructions("wifi")}

    def password_help(state: HelpState) -> dict:
        return {"reply": _format_instructions("password")}

    def other_help(state: HelpState) -> dict:
        return {"reply": "Is your problem about Wi-Fi or about a password?"}

    def clarify_problem(state: HelpState) -> dict:      # NEW: node that asks which problem
        return {"reply": "Is the problem connecting to Wi-Fi, or recovering your account password?"}

    # --- conditional edge: reads state, returns the NAME of the next node (no state change) ---
    def choose_next(state: HelpState) -> str:
        return {
            "wifi": "wifi_help",
            "password": "password_help",
            "both": "clarify_problem",                  # NEW: new branch
            "other": "other_help",
        }[state["category"]]

    g = StateGraph(HelpState)
    g.add_node("read_request", read_request)
    g.add_node("wifi_help", wifi_help)
    g.add_node("password_help", password_help)
    g.add_node("other_help", other_help)
    targets = ["wifi_help", "password_help", "other_help"]
    if clarify:                                         # NEW: add the node only in the new graph
        g.add_node("clarify_problem", clarify_problem)
        targets.append("clarify_problem")
    g.add_edge(START, "read_request")
    g.add_conditional_edges("read_request", choose_next, targets)
    for node in targets:
        g.add_edge(node, END)
    return g.compile()


def run_with_trace(message: str, variant: str = "original") -> dict:
    """Run the graph and record each node visited plus the full state after it."""
    graph = build_graph(variant)
    state: dict = {"message": message}
    steps = []
    for update in graph.stream({"message": message}, stream_mode="updates"):
        for node, changes in update.items():
            state = {**state, **changes}
            steps.append({"node": node, "update": changes, "state_after": dict(state)})
    return {
        "graph_variant": variant,
        "message": message,
        "nodes_visited": ["START"] + [s["node"] for s in steps] + ["END"],
        "steps": steps,
        "final_reply": state.get("reply"),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Part 1 helpdesk graph (no LLM)")
    p.add_argument("--message", required=True)
    p.add_argument("--variant", default="original", choices=["original", "with_clarification"])
    p.add_argument("--trace-json", help="write the trace to this file")
    args = p.parse_args()
    trace = run_with_trace(args.message, args.variant)
    print("Message  :", trace["message"])
    print("Variant  :", trace["graph_variant"])
    print("Route    :", " -> ".join(trace["nodes_visited"]))
    for s in trace["steps"]:
        print(f"  after {s['node']:<16} state = {json.dumps(s['state_after'], ensure_ascii=False)}")
    print("Reply    :\n" + trace["final_reply"])
    if args.trace_json:
        with open(args.trace_json, "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()