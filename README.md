# CSS-4007 HW5 — University IT helpdesk with LangGraph

A terminal helpdesk assistant (fictional data) built in stages with LangGraph:

1. **Part 1** — a graph with no LLM (`helpdesk/part1.py`): `read_request` → conditional edge → `wifi_help` / `password_help` / `other_help` (and `clarify_problem` in the changed graph).
2. **Part 2** — a model that chooses tools (`helpdesk/agent.py`, `helpdesk/tools.py`): `find_instructions`, `check_service_status`, `prepare_ticket` (+ `save_user_preference`), with a loop limit.
3. **Part 3** — memory: conversation memory (LangGraph SQLite checkpointer, per `thread_id`) and user memory (SQLite, per `user_id`).
4. **Part 4** — tests, pinned dependencies, GitHub Actions CI.

The original assignment text is in [ASSIGNMENT.md](ASSIGNMENT.md). My answers and results are in [SUBMISSION.md](SUBMISSION.md).

## Setup

Python version used: **3.11.9** (Windows). CI uses Python 3.11.

Windows PowerShell:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux:
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

`requirements.txt` pins the exact versions I used: langgraph 1.2.20, langgraph-checkpoint-sqlite 3.1.3, langchain-core 1.7.6, langchain-openai 1.7.4, openai 3.35.1, python-dotenv 1.2.3, pytest 9.1.1.

### Model and API key

* Part 1 needs no key.
* The **real model** needs an OpenAI API key and a model name that supports function tools. Copy `.env.example` to `.env` and fill in:
  ```
  OPENAI_API_KEY=your-key
  MODEL_NAME=gpt-5.6-luna
  ```
  I used `gpt-5.6-luna` from OpenAI. `.env` is git-ignored. Never commit keys.
* The model is called with `reasoning_effort="none"`. With reasoning turned on, the OpenAI chat completions endpoint refuses function tools for this model.
* If you use another provider, replace the `langchain-openai` adapter in `requirements.txt` and in `helpdesk/agent.py` (function `get_model`).
* Without a key, `--model auto` (the default) uses a clearly labelled **scripted fake model** (`helpdesk/fake_model.py`). It is not an LLM. The tests use it. Use `--model real` to force the real model.

## Run

Part 1 (no LLM):
```powershell
python -m helpdesk.part1 --message "My Wi-Fi password does not work."
python -m helpdesk.part1 --message "My Wi-Fi password does not work." --variant with_clarification
```
The first command runs the original graph. The second runs the changed graph with `clarify_problem`.

Parts 2–3 (model + tools + memory). Several `--message` options go to the same conversation:
```powershell
python -m helpdesk.cli --user demo-user-a --thread s06 --profile normal --model real --message "Show me the Wi-Fi troubleshooting steps." --message "I enabled Wi-Fi and forgot the saved network, but Campus-Demo still will not connect. Check whether Wi-Fi is down. If it is operating, prepare a ticket about this problem."
```
Options: `--user`, `--thread`, `--profile normal|wifi_outage|recovery_outage|status_unavailable`, `--model auto|fake|real`, `--trace-json FILE`, `--max-tool-rounds N`. Without `--message` the program is interactive (an empty line quits).

Restart demo (two separate runs = two processes, same storage):
```powershell
python -m helpdesk.cli --user demo-user-a --thread restart-a --model real --message "Please remember that I prefer replies in Kazakh. My issue is Wi-Fi. I enabled it and tried reconnecting, but it still fails."
python -m helpdesk.cli --user demo-user-a --thread restart-a --model real --message "Which problem and steps did we discuss?"
```

### All supplied scenarios (S01–S14)
```powershell
python -m helpdesk.runner --all
python -m helpdesk.runner --scenario S11
python -m helpdesk.runner --all --model real
```
The runner writes one log per scenario to `outputs/S01.json` … `outputs/S14.json`. It deletes the storage before each scenario (`reset_before`), runs each group of messages in its own process, and starts a **new process** at every `restart_process` event. Each log records the commands, process ids, the model used, nodes, tool requests and results, information sources, the final reply, ticket file names and whether the loop limit was reached.

### Saved logs in `outputs/`

* `S*.json` — logs of the supplied scenarios (Part 1 traces and runner logs). The model used is written inside each log.
* `real-*.json` — runs with the real model (`gpt-5.6-luna`) for Parts 2 and 3.
* `tickets/` — local ticket drafts. They contain only invented demo data. Nothing is ever sent.

## Where memory is saved, and how to reset it

* Default folder: `local-storage/` (change it with the environment variable `HELPDESK_STORAGE_DIR`). It is git-ignored.
  * `checkpoints.sqlite` — conversation memory (LangGraph checkpointer, one conversation per `thread_id`).
  * `user_memory.sqlite` — user memory (reply-language preference, one row per `user_id`).
* Reset everything:
  * Windows PowerShell: `Remove-Item -Recurse -Force local-storage`
  * macOS / Linux: `rm -rf local-storage`
* Ticket drafts go to `outputs/tickets/` (change with `HELPDESK_TICKET_DIR`).

## Tests and CI

```powershell
python -m pytest -q
```
The tests use temporary folders and the scripted fake model, so they need **no API key**. They cover routing, the three tools, ticket rules, the loop limit, memory after a restart (including a real two-process test), and separation between users and between threads. The docstring of each test says what bug it would catch. GitHub Actions (`.github/workflows/tests.yml`) runs the tests on every push. The real-model demonstration is separate and is not part of CI.

## Layout

```
helpdesk/part1.py       Part 1 graph (no LLM) and trace
helpdesk/tools.py       the tools as plain functions
helpdesk/agent.py       model/tools graph, loop limit, storage setup
helpdesk/memory.py      user memory (SQLite)
helpdesk/fake_model.py  scripted fake model for tests and offline runs
helpdesk/cli.py         terminal application
helpdesk/runner.py      scenario runner (S01-S14)
data/                   supplied fixtures
outputs/                saved logs and demo tickets
tests/                  pytest tests
```