# HW5 — My LangGraph helpdesk

## Part 1 — How the graph works

### My graph and state

```
START -> read_request -> choose_next (conditional edge)
                           |-- wifi_help     -> END
                           |-- password_help -> END
                           '-- other_help    -> END
```

The state has three fields:

| Field | What it holds |
| --- | --- |
| `message` | The user's original message. It is never changed. |
| `category` | The category found by `read_request` (`wifi`, `password` or `other`). |
| `reply` | The answer written by a help node. |

What each part reads and changes:

| Part | Reads | Changes |
| --- | --- | --- |
| `read_request` | `message` | `category` |
| `wifi_help` | nothing from the state (it reads `data/helpdesk.json`) | `reply` |
| `password_help` | nothing from the state (it reads `data/helpdesk.json`) | `reply` |
| `other_help` | nothing | `reply` |
| `choose_next` (conditional edge) | `category` | nothing |

**1. What information does each node need to read? What does it change?**
`read_request` reads `message` and changes `category`. The help nodes do not need to read the state. `wifi_help` and `password_help` read the instructions from `data/helpdesk.json`. Every help node changes `reply`. The conditional edge `choose_next` reads `category` and changes nothing.

**2. What is the difference between a node returning an update and a conditional edge choosing the next node?**
A node returns an update. This is a dictionary with the state keys it wants to change, and LangGraph merges it into the state. A conditional edge returns only the name of the next node. It does not change the state.

**3. Does the next node receive only the previous node's update, or the current graph state?**
It receives the current graph state. After `read_request`, the state is `{message, category}`. The next node sees both fields, not only `category`.

**4. What do `START`, `END`, and compiling a graph mean in this program?**
`START` is the entry point. The first edge leaves from it. `END` means the run is finished. `compile()` checks that the graph is valid (the nodes and edges exist) and turns it into an object that I can run.

### Predictions before running

I wrote each prediction from the three routing rules before I ran the code. Then I ran `python -m helpdesk.part1 --message "..."` for each message.

| Message | Predicted route | Actual route | What I learned |
| --- | --- | --- | --- |
| I cannot connect to Wi-Fi. | read_request → wifi_help | START → read_request → wifi_help → END | "Wi-Fi" with a hyphen is found. |
| I forgot my PASSWORD. | read_request → password_help | START → read_request → password_help → END | Upper and lower case do not matter. |
| My laptop screen is broken. | read_request → other_help | START → read_request → other_help → END | Unknown topics go to the node that asks a question. |
| My Wi-Fi password does not work. | read_request → wifi_help | START → read_request → wifi_help → END | The order of the rules decides the route. Wi-Fi is checked first. |

**Both topics.** When a message mentions both Wi-Fi and a password, the graph sends it to `wifi_help`. The reason is rule 1: `read_request` checks Wi-Fi first and sets `category = "wifi"`. The password rule is never checked. So the user may get Wi-Fi instructions for a password problem.

### My change to the graph

I added a new node `clarify_problem`. When both topics appear, the request goes there. It asks which problem the user wants to solve first.

```
START -> read_request -> choose_next (conditional edge)
                           |-- wifi_help        -> END
                           |-- password_help    -> END
                           |-- clarify_problem  -> END   (new: both topics)
                           '-- other_help       -> END
```

What I changed in the code:
1. `read_request` sets `category = "both"` when the message contains both Wi-Fi and password. This check comes before the Wi-Fi rule.
2. `choose_next` sends `both` to `clarify_problem`.
3. The new node `clarify_problem` writes a question into `reply`.

New execution trace for "My Wi-Fi password does not work.":

```
Route: START -> read_request -> clarify_problem -> END
after read_request:    {"message": "My Wi-Fi password does not work.", "category": "both"}
after clarify_problem: {"message": "My Wi-Fi password does not work.", "category": "both",
                        "reply": "Is the problem connecting to Wi-Fi, or recovering your account password?"}
```

**The difference.** Before the change, this message went to `wifi_help` and the user got Wi-Fi instructions. After the change, it goes to `clarify_problem` and the user gets a question. The route in the graph is different. It is not only a different final sentence.

**What LangGraph controls, and what my functions decide.**
LangGraph controls how the program runs. It starts at `START`, runs one node at a time, merges each update into the state, follows the edge that the conditional function returns, and stops at `END`. My own Python functions decide what things mean. They find the topic in the message, decide which rule has priority, set the category, return the name of the next node and write the replies. There is no model in this part, so all decisions are made by my code.

## Part 2 — Model and tools

### The loop

```
START -> load_user_memory -> agent --(no tool request)--------------------> END
                               |  ^
        (tool request, < 4)    |  |  the tool result goes back to the model
                               v  |
                             tools
agent --(tool request, 4 rounds used)--> limit_reached -> END
```

1. The model requests a tool. This is a message with a tool name and arguments.
2. My `tools` node runs the tool function.
3. The result is added to the messages as a tool message.
4. The `agent` node calls the model again. It either requests another tool or answers.

**Loop limit.** The limit is 4 tool rounds per user message (`MAX_TOOL_ROUNDS` in `helpdesk/agent.py`). It is enforced in the conditional edge `route_after_agent`. If the model asks for a tool and 4 rounds are already used, the graph goes to `limit_reached` and stops. A test with a model that always asks for a tool (`test_loop_limit_stops_a_runaway_model`) checks this.

### The tools

`find_instructions`, `check_service_status` and `prepare_ticket` are normal Python functions in `helpdesk/tools.py`. Each works without the agent. I called them directly:

```
find_instructions('Wi-Fi')['instruction_id']      -> GUIDE-WIFI
check_service_status('wifi', 'wifi_outage')['status'] -> outage
prepare_ticket('', [])  -> {'created': False, 'error': 'missing_information',
                            'missing': ['problem description', 'steps already tried']}
```

The model only chooses the tool and its arguments. My program supplies the user id, the thread id and the status snapshot, so the model cannot choose them.

### Questions

**1. How does the graph decide between running a tool and ending with an answer?**
The conditional edge `route_after_agent` looks at the last message from the model. If it has no tool request, the run ends. If it has a tool request and fewer than 4 rounds were used, the graph goes to `tools`. If 4 rounds were used, it goes to `limit_reached`.

**2. Which component requests a tool, and which component actually executes it?**
The model requests it. It only returns the tool name and the arguments. My `tools` node executes the function.

**3. What changes in the state after a tool result returns?**
A tool message with the result is added to `messages`, and `tool_rounds` increases by 1. The next model call sees this result.

**4. What makes this part different from the fixed routing rules in Part 1?**
In Part 1, my keyword rules chose the route. Here the model chooses which tool to call and when to stop, and its choice depends on the tool results. For example, the status check decides whether a ticket is made.

### Real run

- **Provider and model:** OpenAI, `gpt-5.6-luna`, with `reasoning_effort="none"`. With reasoning on, the API refused function tools on the chat completions endpoint, so I turned reasoning off.
- **Logs:** `outputs/real-S06.json`, `outputs/real-S07.json`, `outputs/real-S08.json`.
- The scripted fake model was used only for tests and for the first logs. It is not an LLM.

The same conditional request with three status snapshots:

| Snapshot | Tools called by the model | Result |
| --- | --- | --- |
| normal (S06) | `check_service_status` → `prepare_ticket` | Status `operational`. Local draft `TCK-20261109-062349-98c871.json`. `steps_tried`: "Enabled Wi-Fi.", "Forgot the saved Campus-Demo network." |
| wifi_outage (S07) | `check_service_status`, `find_instructions` | Status `outage`. No ticket. No repair time, because the data has none. |
| status_unavailable (S08) | `check_service_status` | Status `unknown`. No ticket. The model did not say Wi-Fi is operating. It asked if I want a draft. |

Differences from the fake model: in S07 the real model also called `find_instructions` in the same step, which was not needed. In S06 it did not put `GUIDE-WIFI` into `reference_ids`. A real model can behave a little differently each time, so my saved logs are the evidence for what happened.

## Part 3 — Memory

I use two separate kinds of memory.

| | Conversation memory | User memory |
| --- | --- | --- |
| What it holds | messages, current problem, steps already tried | the preference for the reply language |
| Key | `thread_id` | `user_id` |
| How it is saved | LangGraph checkpointer (`SqliteSaver`) | my own SQLite table in `helpdesk/memory.py` |
| File | `local-storage/checkpoints.sqlite` | `local-storage/user_memory.sqlite` |
| Lives | in one conversation | in all conversations of this user |

**How it works.** The checkpointer saves the graph state after each step. When a new message arrives with the same `thread_id`, the graph loads the saved messages and adds the new one. User memory is read by the node `load_user_memory` at the start of every message, and it is put into the system prompt. It is written by the tool `save_user_preference`, which the model calls when the user asks to remember something. Only the key `reply_language` is allowed.

**`thread_id` and user identifier.** A `thread_id` identifies one conversation. One user can have many conversations, and each has its own history. A `user_id` identifies the person and selects the user memory, which is shared by all of that person's conversations. My program sets both values (`--user`, `--thread`). The model cannot choose them. In `save_user_preference` the user id comes from the program's config, not from the model's arguments, so the model cannot write to or read another user's memory.

**Retrieval and memory.** Looking up Wi-Fi instructions is retrieval. The same reference file, `data/helpdesk.json`, is read for everyone. Recalling the language is memory. The user told me this earlier, it is stored per user, and it exists nowhere else.

All runs below used the real model `gpt-5.6-luna` (OpenAI). Storage was deleted before each scenario.

| Situation | Command used | Log file | What happened |
| --- | --- | --- | --- |
| Refer to an earlier message | `python -m helpdesk.cli --user demo-user-a --thread s10 --model real --message "I cannot connect to Wi-Fi. I enabled it and forgot the saved network, but reconnecting failed." --message "Which steps did I already try?"` | `outputs/real-S10.json` | In the second message the checkpoint gave back 5 messages. The assistant listed: enabled Wi-Fi, forgot the saved network, tried reconnecting. Source: conversation memory. |
| Close, restart and resume | Two separate runs with `--thread restart-a` (first: "Please remember that I prefer replies in Kazakh. My issue is Wi-Fi..."; second: "Which problem and steps did we discuss?") | `outputs/real-S11-run1.json`, `outputs/real-S11-run2.json` | The process ids were different (16440 and 15780). The second run restored 7 messages from the checkpoint and loaded `reply_language: Kazakh` from user memory. It answered in Kazakh about the Wi-Fi problem and the steps. |
| Same user, new conversation | Thread `preference-a1` (save the preference), then thread `preference-a2` ("Which language did I ask you to use? What can you help with?") | `outputs/real-S12-run1.json`, `outputs/real-S12-run2.json` | The new thread restored 0 messages (a separate conversation), but user memory had `Kazakh`. The answer named the language and what the helpdesk can do, in Kazakh. Source: user memory. |
| Different user | `demo-user-a` saves the preference in `isolation-a`; then `demo-user-b` in `isolation-b` asks "Have I told you a preferred language or a previous problem?" | `outputs/real-S13-run1.json`, `outputs/real-S13-run2.json` | `demo-user-b` had empty user memory and 0 restored messages. The assistant said it has no saved language or previous problem. Nothing from `demo-user-a` appeared. |

**What was read from where.**
- Conversation memory: S10 (second message) and S11 (second run).
- User memory: S11 (second run) and S12 (second run). The log shows `user memory: {"reply_language": "Kazakh"}` in `load_user_memory`.
- Reference file `data/helpdesk.json`: the `find_instructions` results, in the first-turn runs.

## Part 4 — Running and checking my work

TODO: point to the README setup steps, package versions, memory-reset instructions, tests and GitHub Actions workflow. Explain which mistake each test catches and which runs use a fake model.

## Choices and limitations

TODO: explain the storage and libraries I chose, why they fit this task, and what still does not work reliably.

## Supplied scenarios — my actual results

| Scenario | Command or manual steps | Log file | What happened / what I changed |
| --- | --- | --- | --- |
| S01 — Simple Wi-Fi route | | | |
| S02 — Case-insensitive password route | | | |
| S03 — Unsupported request | | | |
| S04 — Two topics before the graph change | | | |
| S05 — Two topics after adding clarification | | | |
| S06 — Instructions then local ticket | | | |
| S07 — The same request during a Wi-Fi outage | | | |
| S08 — Status source unavailable | | | |
| S09 — Missing ticket details | | | |
| S10 — Use the current conversation | | | |
| S11 — Persist and recall after restart | | | |
| S12 — Preference across threads without replay | | | |
| S13 — Do not share memory between users | | | |
| S14 — Password recovery outage | | | |
