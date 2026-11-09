"""Terminal application for Parts 2-3.

One message:   python -m helpdesk.cli --user demo-user-a --thread t1 --profile normal --message "..."
Several msgs:  repeat --message (they go to the same conversation in ONE process)
Interactive:   omit --message and type messages; an empty line quits.
Options: --model fake|real|auto, --trace-json FILE (save the trace), --max-tool-rounds N
"""
import argparse
import json
import os

from dotenv import load_dotenv

from .agent import MAX_TOOL_ROUNDS, build_app, get_model, open_storage


def _short(text: str, n: int = 300) -> str:
    return text if len(text) <= n else text[:n] + "..."


def run_turn(app, user_id, thread_id, profile, message, model_desc, memory) -> dict:
    config = {"configurable": {"user_id": user_id, "thread_id": thread_id, "status_profile": profile}}
    before = app.get_state(config).values.get("messages", [])
    events = []
    final_reply, limit_reached, ticket_files = None, False, []
    sources = {"conversation_state": {"restored_messages_from_checkpoint": len(before)}}
    for update in app.stream({"messages": [("user", message)]}, config, stream_mode="updates"):
        for node, changes in update.items():
            ev = {"node": node}
            if node == "load_user_memory":
                ev["user_memory_loaded"] = changes["user_memory"]
                sources["user_memory"] = changes["user_memory"]
            elif node == "agent":
                msg = changes["messages"][-1]
                if msg.tool_calls:
                    ev["model_tool_requests"] = [{"tool": c["name"], "args": c["args"]} for c in msg.tool_calls]
                else:
                    ev["model_answer"] = msg.content
                    final_reply = msg.content
            elif node == "tools":
                ev["tool_results"] = []
                for m in changes["messages"]:
                    data = json.loads(m.content)
                    ev["tool_results"].append({"tool": m.name, "result": data})
                    if data.get("source"):
                        sources.setdefault("reference_file", []).append(data["source"])
                    if m.name == "save_user_preference" and data.get("saved"):
                        sources["user_memory_written"] = {data["key"]: data["value"]}
                    if m.name == "prepare_ticket" and data.get("created"):
                        ticket_files.append(data["filename"])
            elif node == "limit_reached":
                limit_reached = True
                final_reply = changes["messages"][-1].content
                ev["model_answer"] = final_reply
            events.append(ev)
    return {"user_id": user_id, "thread_id": thread_id, "status_profile": profile, "model": model_desc,
            "user_message": message, "events": events, "information_sources": sources,
            "final_reply": final_reply, "ticket_files": ticket_files, "loop_limit_reached": limit_reached,
            "pid": os.getpid()}


def print_turn(t: dict) -> None:
    print(f"\n> {t['user_message']}")
    for ev in t["events"]:
        line = f"  [{ev['node']}]"
        if "user_memory_loaded" in ev:
            line += f" user memory: {json.dumps(ev['user_memory_loaded'], ensure_ascii=False)}"
        for r in ev.get("model_tool_requests", []):
            line += f" model requests {r['tool']}({json.dumps(r['args'], ensure_ascii=False)})"
        for r in ev.get("tool_results", []):
            line += f" {r['tool']} -> {_short(json.dumps(r['result'], ensure_ascii=False), 160)}"
        if "model_answer" in ev:
            line += " model answers"
        print(line)
    print(f"Helpdesk: {t['final_reply']}")
    if t["ticket_files"]:
        print(f"  (local ticket draft: {', '.join(t['ticket_files'])})")
    if t["loop_limit_reached"]:
        print("  (loop limit reached)")


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description="University IT helpdesk (LangGraph)")
    p.add_argument("--user", required=True, help="user identifier, e.g. demo-user-a (set by the app, not the model)")
    p.add_argument("--thread", required=True, help="conversation identifier, e.g. s06")
    p.add_argument("--profile", default="normal",
                   choices=["normal", "wifi_outage", "recovery_outage", "status_unavailable"])
    p.add_argument("--message", action="append", help="a message to send (repeatable)")
    p.add_argument("--model", default="auto", choices=["auto", "fake", "real"])
    p.add_argument("--max-tool-rounds", type=int, default=MAX_TOOL_ROUNDS)
    p.add_argument("--trace-json", help="write the trace of this run to a JSON file")
    args = p.parse_args()

    model, model_desc = get_model(args.model)
    checkpointer, memory, conn = open_storage()
    app = build_app(model, memory, checkpointer, args.max_tool_rounds)
    print(f"model: {model_desc} | user: {args.user} | thread: {args.thread} | status profile: {args.profile} | pid: {os.getpid()}")
    turns = []
    try:
        if args.message:
            for msg in args.message:
                turns.append(run_turn(app, args.user, args.thread, args.profile, msg, model_desc, memory))
                print_turn(turns[-1])
        else:
            while True:
                msg = input("you> ").strip()
                if not msg:
                    break
                turns.append(run_turn(app, args.user, args.thread, args.profile, msg, model_desc, memory))
                print_turn(turns[-1])
    finally:
        memory.close()
        conn.close()
    if args.trace_json:
        with open(args.trace_json, "w", encoding="utf-8") as f:
            json.dump(turns, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
