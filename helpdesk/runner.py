"""Run the supplied scenarios (data/scenarios.json) and save one log per scenario in outputs/.

    python -m helpdesk.runner --all
    python -m helpdesk.runner --scenario S11 [--model fake|real|auto]

Every message of Parts 2-3 is run through helpdesk.cli in a SUBPROCESS. A `restart_process`
event ends the current process, so the next message really runs in a new process (new PID)
against the same storage. If reset_before is true, the storage directory is deleted first.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .common import ROOT, load_json, storage_dir

OUTPUTS = ROOT / "outputs"


def _run(cmd: list, trace_path: Path) -> list:
    # Force UTF-8 so Kazakh letters survive the pipe between processes on Windows.
    env = {**os.environ, "PYTHONUTF8": "1"}
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{proc.stderr}")
    with open(trace_path, encoding="utf-8") as f:
        return json.load(f)


def _quote(parts: list) -> str:
    return " ".join(f'"{p}"' if (" " in p or not p) else p for p in parts)


def run_scenario(sc: dict, model_kind: str) -> dict:
    py = sys.executable
    tmp = Path(tempfile.mkdtemp())
    log = {"scenario": sc["id"], "title": sc["title"], "part": sc["part"],
           "status_profile": sc["status_profile"], "reset_before": sc["reset_before"],
           "commands": [], "segments": []}
    if sc["part"] == 1:
        variant = sc.get("graph_variant", "original")
        log["graph_variant"] = variant
        for ev in sc["events"]:
            cmd = [py, "-m", "helpdesk.part1", "--message", ev["message"], "--variant", variant,
                   "--trace-json", str(tmp / "t.json")]
            trace = _run(cmd, tmp / "t.json")
            log["user_id"], log["thread_id"] = ev["user_id"], ev["thread_id"]
            log["commands"].append("python -m helpdesk.part1 --message " + _quote([ev["message"]]) + f" --variant {variant}")
            log["segments"].append({"trace": trace})
            log["final_reply"] = trace["final_reply"]
        return log

    if sc["reset_before"]:
        shutil.rmtree(storage_dir(), ignore_errors=True)
    segments, current = [], None
    for ev in sc["events"]:
        if ev["action"] == "restart_process":
            current = None
            segments.append({"restart_process": True})
        elif current and (current["user_id"], current["thread_id"]) == (ev["user_id"], ev["thread_id"]):
            current["messages"].append(ev["message"])
        else:
            current = {"user_id": ev["user_id"], "thread_id": ev["thread_id"], "messages": [ev["message"]]}
            segments.append(current)
    for i, seg in enumerate(segments):
        if seg.get("restart_process"):
            log["segments"].append({"event": "restart_process (previous process ended; next run is a new process, same storage)"})
            continue
        cmd = [py, "-m", "helpdesk.cli", "--user", seg["user_id"], "--thread", seg["thread_id"],
               "--profile", sc["status_profile"], "--model", model_kind, "--trace-json", str(tmp / f"s{i}.json")]
        shown = ["python", "-m", "helpdesk.cli", "--user", seg["user_id"], "--thread", seg["thread_id"],
                 "--profile", sc["status_profile"]]
        for m in seg["messages"]:
            cmd += ["--message", m]
            shown += ["--message", m]
        turns = _run(cmd, tmp / f"s{i}.json")
        log["commands"].append(_quote(shown))
        log["segments"].append({"user_id": seg["user_id"], "thread_id": seg["thread_id"], "process_id": turns[0]["pid"],
                                "model": turns[0]["model"], "turns": turns})
    last = [s for s in log["segments"] if "turns" in s][-1]["turns"][-1]
    log["final_reply"] = last["final_reply"]
    log["ticket_files"] = [f for s in log["segments"] for t in s.get("turns", []) for f in t["ticket_files"]]
    log["loop_limit_reached"] = any(t["loop_limit_reached"] for s in log["segments"] for t in s.get("turns", []))
    return log


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario")
    p.add_argument("--all", action="store_true")
    p.add_argument("--model", default="fake", choices=["fake", "real", "auto"])
    args = p.parse_args()
    scenarios = load_json("scenarios.json")["scenarios"]
    chosen = scenarios if args.all else [s for s in scenarios if s["id"] == args.scenario]
    if not chosen:
        raise SystemExit("choose --all or --scenario S01..S14")
    OUTPUTS.mkdir(exist_ok=True)
    for sc in chosen:
        log = run_scenario(sc, args.model)
        out = OUTPUTS / f"{sc['id']}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        print(f"{sc['id']} ({sc['title']}) -> {out.relative_to(ROOT)} | reply: {str(log['final_reply'])[:90]!r}")


if __name__ == "__main__":
    main()