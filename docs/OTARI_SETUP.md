# Setting up Otari for Mollet

Do these once, in order, in the Otari dashboard. After each step, run the matching check:

```bash
python -m scripts.check_otari <check>   # models | users | budget | code | search | guardrail | mcp | tools
```

Write down anything surprising in [FEEDBACK.md](../FEEDBACK.md) as you go.

## 1. Pick three open-weight models

**Models** tab: filter for open-weight models and pick from *different families*:

| Role | Pick | Used for |
| --- | --- | --- |
| Hinter A + Hinter B | two small, cheap chat models (e.g. a Llama or Gemma and a Mistral) | rungs 1–3, as a fallback chain |
| Mentor + cheaper tier | a larger chat model (e.g. DeepSeek or Qwen) and one cheaper model | rungs 4–5 |
| Grader | an open-weight **coding** model (e.g. Qwen Coder or Devstral) | reviewing submissions |

Note each model's id exactly as the Models tab shows it.

## 2. Routing policies (feature: routing and fallbacks)

In the workspace, **Routing → Policies**:

1. **`mollet-hinter`**, strategy **Add a fallback chain**: Hinter A first, then Hinter B.
2. **`mollet-mentor`**, strategy **Tier down when the budget fills up**: the Mentor model, switching to the cheaper model at 80%.

A request selects a policy by sending the policy name as `model` (`"model": "mollet-hinter"`). The response body keeps the policy name; the `Otari-Model` header says which model actually answered, and `Otari-Fallback: true` says a later candidate served it. Mollet shows both in every hint's **Otari trace**.

For the Grader, either create a one-model policy `mollet-grader` or set `MOLLET_GRADER_MODEL` to the model id directly.

**Demo the fallback:** edit `mollet-hinter` so its first entry is a model your workspace can't serve (or switch that model off), ask for a hint, and show `fallback: yes` with Hinter B as "served by". Put it back afterwards.

## 3. Wallets: end-user budgets and a service key (feature: per-user budgets)

1. **Spend & budgets**: create a budget named `mollet-weekly-wallet`, `max_budget` **$0.05**, weekly reset (Mondays, UTC midnight). For the demo, a tiny value such as **$0.01** makes the wallet run out on camera.
2. **API keys → Create key → Advanced**: tick **Service key**. Under **End-user budgets** pick `mollet-weekly-wallet`, and choose it as the **Default end-user budget**. Only an organization owner or admin can create one.
3. Put the key in `.env` as `OTARI_API_KEY`.

Each student id Mollet sends in `user` becomes an end user with its own copy of that budget. Check: `python -m scripts.check_otari users`.

## 4. The class cap (feature: budgets)

**Spend & budgets**: add a **workspace** budget, weekly, e.g. **$1.00**. Set `MOLLET_CLASS_BUDGET_USD` to the same number; Otari reports only what remains of a workspace cap, so Mollet needs the size to draw the bar. When it runs out, Otari refuses with `budget_exceeded` and a non-`user` scope, and every student sees "Class budget reached". Check: `python -m scripts.check_otari budget`.

## 5. Code execution

Workspace **Tools → Code execution → Allowed**. Set an execution timeout of at least 10 seconds. Check: `python -m scripts.check_otari code` (it computes 23!).

## 6. Web search

Workspace **Tools → Web search**: make sure it is allowed. Check: `python -m scripts.check_otari search`.

## 7. Guardrails

**Organization → Guardrails** (owner or admin): configure a guardrail that detects personal information (PII) and one for content safety, and **mandate** both on the Mollet workspace in **block** mode. Use **Test a guardrail** to try a phone number.

To also send request-level profiles, list the profile names in `MOLLET_GUARDRAILS` (see `GET /api/v1/tool-settings/guardrails/profiles`, shown by `check_otari guardrail`). Check: `python -m scripts.check_otari guardrail` should print `403 guardrail_violation`.

Say on the video which checks are Otari guardrails (PII, content safety) and which are Mollet's own app rules (never giving the full answer; the optional `MOLLET_APP_PII_PRECHECK`).

## 8. The classroom MCP server

Otari's servers must reach the MCP server over the internet, so it has to be deployed (a laptop's `localhost` won't work).

1. Deploy Mollet. On [Render](https://render.com): **New → Blueprint**, pick this repo and branch `otari-hackathon`; `render.yaml` sets it up. Add `OTARI_API_KEY` when asked. Any host with HTTPS works (Railway, Fly.io, or a `cloudflared` tunnel for a quick test).
2. Check it answers: `curl -s https://<your-app>/healthz`.
3. Workspace **Tools → MCP servers → Add**: URL `https://<your-app>/classroom/mcp`, transport streamable HTTP, and the bearer token = your `MOLLET_MCP_TOKEN` (Render generates one; copy it from the service's environment).
4. Copy the new server's id into `MOLLET_MCP_SERVER_ID` (in `.env` locally and in Render's environment) and restart.
5. Check: `python -m scripts.check_otari mcp` should show an MCP call to `get_problem`.

The deployed app and the MCP server share one SQLite file, so `get_student_history` sees the mistakes the Grader recorded. Record the demo against the deployed app so MCP sees real history. Render's free disk is wiped on redeploy, which is fine for a demo.

## 9. Final check

Run `python -m scripts.check_otari` (all checks), then open `/status` in the app: all eight features should read **In use** after one pass through the demo.
