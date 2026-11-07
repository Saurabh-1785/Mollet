# Otari feedback log

Add a row whenever something surprises, annoys or delights you. Types: worked well · friction/bug · missing feature · tempted to skip Otari.

The first rows are things noticed while reading the docs to design Mollet (Nov 7, 2026). Confirm each one against the live product before you submit it, and rewrite in your own words.

| Date | What happened | Type | Steps to reproduce |
| --- | --- | --- | --- |
| 2026-11-07 | Quickstart writes model ids as `provider/model` (`deepseek/deepseek-v4-pro-0813`); the routing guide writes `provider:model` (`openai:gpt-4o`). Unclear which the hosted gateway expects, or if both work. | friction | Compare docs.otari.ai/getting-started/quickstart.md with /how-to-guides/create-a-multi-provider-routing.md |
| 2026-11-07 | The hosted routing guide doesn't say how a request picks a policy. The self-hosted routing page does: send the policy name as `model`. | friction (docs gap) | Read create-a-multi-provider-routing.md, then otari/for-operators/routing.md |
| 2026-11-07 | Hosted Budgets page doesn't give the refusal's status or code. The API reference does (`403`, `Otari-Error-Code: budget_exceeded`, `Otari-Budget-Scope`, `Retry-After`), and those headers made the "refills Monday" message easy. | friction (docs gap) / worked well | docs.otari.ai/learn/budgets.md vs the "Error codes" section of the API reference |
| 2026-11-07 | Configure-code-execution page explains the dashboard switch but not the request shape. `POST /api/v1/code/execute` (run code with no model) is only in the API reference, and it was the most useful endpoint for trustworthy grading. | friction (docs gap) / worked well | docs.otari.ai/tools/configure-code-execution.md |
| 2026-11-07 | Chat API reference documents no 200 response schema, so `otari_tool_calls` (search sources, code stdout, MCP output) is only described in the tools/API-reference prose. | friction (docs gap) | docs.otari.ai/api-reference/chat.md |
| 2026-11-07 | Inference guardrails doc names only the `prompt-injection` profile; how to get PII detection on hosted otari.ai isn't stated. | missing / docs gap | docs.otari.ai/otari/for-integrators/guardrails.md |
| 2026-11-07 | Routing headers (`Otari-Model`, `Otari-Fallback`, `Otari-Attempt-Count`) plus inline `usage.cost_usd` made the per-hint trace and real hint prices possible without any extra calls. | worked well | Any chat completion through a policy |
| 2026-11-07 | End users on a service key gave per-student wallets with no key per student, and `GET /end-users?external_id=` returns their spend and reset time. | worked well | docs.otari.ai/api-reference/end-users.md |
| | | | |

## Written feedback (draft answers here, in your own words)

**1. When were you most tempted to skip Otari and call the provider directly? What happened?**

**2. What did you end up building yourself that Otari should have done for you?**

Candidates from building Mollet: an app-level "does this hint contain the solution?" check (an output guardrail; the docs say `on: output` is accepted but not enforced yet); drawing the class-budget bar needs the cap size, since `GET /key/budget` reports only `remaining_usd` for workspace caps.

**3. If the rules hadn't required Otari, would you have continued using it? Why or why not?**

## Feedback video (3–5 min, your own voice) covers

1. What I built with Otari and which features (walk through on screen)
2. What worked well
3. What didn't work (bugs, friction, steps to reproduce)
4. What's missing and what I'd change
