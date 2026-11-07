# Mollet

**A hint wallet for learning to code.** Mollet is a mentor that gives the smallest useful hint first and never does the work for you. Each student has a small weekly wallet, every hint has a price, and the price climbs with each rung of the hint ladder. Running out of hints makes students think before they ask, so the budget becomes part of how the app teaches.

Built for MozFest **Developers Wilding: Online** on [Otari](https://otari.ai), Mozilla.ai's open-source AI gateway. All models are open-weight.

| | |
| --- | --- |
| Hackathon branch | `otari-hackathon` |
| Stack | Python 3.12+, FastAPI, server-rendered HTML, SQLite, MCP Python SDK |
| Otari features used | 8: multiple models, per-user budgets, budgets, routing and fallbacks, code execution, guardrails, web search, MCP |

## How it works

A student picks a beginner Python problem, writes code, and can ask for help one rung at a time:

| Rung | Name | What the student gets | Model | Otari tools |
| --- | --- | --- | --- | --- |
| 1 | Point | Names the concept and links one official docs page | Hinter (cheap) | web search, `max_uses: 1` |
| 2 | Explain | Explains the missing concept on a *different* example | Hinter | MCP |
| 3 | Approach | 3 to 5 plain-English steps, no code | Hinter | MCP |
| 4 | Sketch | Pseudocode with `___` blanks that won't run as-is | Mentor (stronger, pricier) | MCP |
| 5 | Walk-through | Only the hardest part, at most 3 lines of code | Mentor | MCP |

- **Prices are real.** The price on each rung is the average of what Otari actually billed for that rung (`usage.cost_usd`). Bigger models cost more, so the later rungs cost more.
- **Wallets are real.** Each student is an Otari *end user* on one service key, with their own weekly budget. When a wallet is empty, Otari itself refuses the next hint (`403 budget_exceeded`, scope `user`), and the student sees "Wallet empty · refills Monday".
- **Checking is free and real.** "Run hidden tests" runs the student's function against hidden tests in Otari's code-execution sandbox. Pass or fail comes from real output, not from a model saying "looks right". A second open-weight model, the Grader, reads those results and writes feedback without giving the fix. Grading is billed to the class, so a student with an empty wallet can still submit.
- **Never the answer.** A hint whose code passes the hidden tests in the sandbox is caught, rewritten, and stripped of code if needed. That is Mollet's own app rule, not an Otari guardrail.
- **Teachers see independence, not just spend.** The independence score for a solved problem is `1 − (sum of hint levels used before the first pass ÷ 15)`, averaged and shown as 0 to 100. Solving with no hints scores 100.

## Otari features and where they are in the code

| # | Rubric feature | What Mollet does with it | Code |
| --- | --- | --- | --- |
| 1 | Multiple models, distinct roles | Hinter (rungs 1–3), Mentor (rungs 4–5) and Grader (a coding model) are separate open-weight models with separate jobs | [`config.py`](mollet/config.py), [`hints.model_for`](mollet/hints.py), [`grader.grade`](mollet/grader.py) |
| 2 | Per-user budgets | One service key. Every hint sets `user` to the student id, so Otari bills that student's end-user budget. The wallet bar reads `spend` and `max_budget` from `GET /end-users` and `GET /end-user-budgets` | [`otari.Otari.chat`](mollet/otari.py), [`wallet.wallet`](mollet/wallet.py) |
| 3 | Budgets / spending limits | A weekly workspace budget is the teacher's cap for the class. `GET /key/budget` drives the teacher view; a refusal with any non-`user` scope shows "Class budget reached" | [`wallet.class_budget`](mollet/wallet.py), [`main.refusal`](mollet/main.py) |
| 4 | Routing and fallbacks | `mollet-hinter` is a fallback-chain policy; `mollet-mentor` tiers down to a cheaper model as the budget fills. Every hint's "Otari trace" shows `Otari-Model`, `Otari-Fallback` and `Otari-Attempt-Count` | [`otari.Otari.chat`](mollet/otari.py), [`mollet.js traceHtml`](mollet/static/js/mollet.js) |
| 5 | Code execution | `POST /code/execute` runs hidden tests; the Grader may run its own checks with `{"type": "otari_code_execution"}`; hints are checked for leaked solutions in the sandbox | [`grader.run_tests`](mollet/grader.py), [`hints.runs_as_solution`](mollet/hints.py) |
| 6 | Guardrails | Organization guardrails in **block** mode (PII, content safety) plus optional request-level profiles (`guardrails: [{profile, mode: "block"}]`). `403 guardrail_violation` becomes a friendly "blocked to keep you safe" message | [`hints.request_hint`](mollet/hints.py), [`main.refusal`](mollet/main.py) |
| 7 | Web search | Rung 1 sends `{"type": "otari_web_search", "max_uses": 1}` and turns `otari_tool_calls[].sources` into a docs link card | [`hints.request_hint`](mollet/hints.py) |
| 8 | MCP | Mollet's own classroom MCP server (`get_problem`, `get_student_history`) over streamable HTTP at `/classroom/mcp`. Rungs 2–5 pass its id in `mcp_server_ids`, so hints can say "Last time you mixed up `=` and `==`" | [`mcp_server.py`](mollet/mcp_server.py), [`hints.build_messages`](mollet/hints.py) |

The **Otari status** page (`/status`) checks all eight live against the gateway and shows where each one is used.

The Otari key lives only on the server. The browser talks to Mollet, and Mollet talks to Otari.

## Run it

```bash
git clone https://github.com/Saurabh-1785/Mollet.git
cd Mollet && git checkout otari-hackathon
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # add your Otari service key, see docs/OTARI_SETUP.md
python -m scripts.check_otari # checks every Otari feature with your key
uvicorn mollet.main:app --reload
```

Open http://localhost:8000. Switch students from the top bar; the teacher view is at `/teacher`.

- **Otari setup** (service key, budgets, routing policies, guardrails, code execution, MCP): [docs/OTARI_SETUP.md](docs/OTARI_SETUP.md)
- **Deploy** (needed for MCP, since Otari must reach the server over HTTPS): `render.yaml` and `Dockerfile` are included; see the setup guide.
- **Tests:** `pytest` runs the full flow (grading, the ladder, wallet drain, guardrail block, leak check, MCP) against an offline mock of the documented Otari responses. The mock is for development only; the UI shows a banner when it is on.

## Project layout

```
mollet/
  main.py          FastAPI routes, refusal messages, MCP mount
  otari.py         Otari client: chat, code execution, end users, key budget
  hints.py         the hint ladder, prompts, "never the answer" checks
  grader.py        sandbox test harness + Grader model
  wallet.py        wallets (end-user budgets) and the class cap
  mcp_server.py    classroom MCP server (streamable HTTP)
  problems.py      problems and hidden tests
  db.py            SQLite: students, attempts, hints, refusals, independence score
  templates/, static/   UI on Otari's design tokens and Mozilla fonts
scripts/check_otari.py  day-1 feature checks against your key
tests/                  pytest suite
```

## Credits

UI colors follow Otari's own design tokens. Fonts: Mozilla Text, Mozilla Headline and Fira Code, under the SIL Open Font License 1.1 (licenses in `mollet/static/fonts/`).
