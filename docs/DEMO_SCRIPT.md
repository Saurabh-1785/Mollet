# Demo video script (aim 4:30, stay under 5:00)

Your own screen and your own voice; no AI voice or AI video. Say each **feature name** out loud the moment it appears on screen. Record against the **deployed** app with the real Otari key (never with `MOLLET_MOCK`).

**Before recording**
- Reset: fresh database (redeploy, or delete `mollet.db` locally) so wallets and history start clean.
- Set the wallet budget to about $0.01 so one student runs dry on camera.
- Give Asha one earlier mistake: submit buggy `count_vowels` once (forgets upper-case), so MCP has history to recall.
- Open in tabs: Mollet `/learn/student_001/count-vowels`, `/teacher`, `/status`; Otari dashboard Usage, Routing → Policies, Spend & budgets, Tools → MCP servers.

| Time | On screen | Say (in your own words) |
| --- | --- | --- |
| 0:00–0:30 | Learn page, the ladder | Students paste AI answers and learn nothing. I wanted a mentor that gives the smallest useful hint and never does the work, so I built Mollet. Hints cost money from a small wallet, so students think before asking. |
| 0:30–1:15 | Asha asks for hints 1 → 3; open the Otari trace | Hint 1 links the real Python docs: **web search**, capped at one search. Hint 2 remembers her earlier mistake: that came from my own **MCP** server. Prices rise per rung because rungs 4–5 use a bigger model: **multiple models**, Hinter, Mentor and Grader. |
| 1:15–2:00 | Asha's wallet bar; switch to Ben, his wallet untouched; back to Asha, keep asking until refused | Every student is an Otari end user on one service key, so each has their own wallet: **per-user budgets**. Asha's is empty, so Otari refuses: "Wallet empty, refills Monday". Ben's is untouched. |
| 2:00–2:45 | Run hidden tests on buggy code → real failing table → fix → all pass | The Grader doesn't guess. The code runs against hidden tests in Otari's sandbox: **code execution**. A second open-weight coding model writes the feedback. Checking is free, even with an empty wallet. |
| 2:45–3:20 | Hint trace `fallback: yes`; dashboard routing policies | **Routing and fallbacks**: I broke the first Hinter model, and the second one answered (served-by and the Otari-Fallback header). The Mentor tiers down to a cheaper model when the budget fills. |
| 3:20–3:50 | Ben types a phone number into "What are you stuck on?" → blocked | **Guardrails** in block mode keep kids' data out of the model. Never giving the full answer is my own app rule: if a hint's code would pass the tests, Mollet rewrites it. |
| 3:50–4:20 | `/teacher`; Otari dashboard budget status | The class cap is a workspace **budget**. The teacher sees each wallet and the independence score: problems solved with few or no hints. |
| 4:20–4:30 | `/status` page, repo URL, branch `otari-hackathon` | Two-plus open-weight models, eight Otari features. Repo and branch on screen. |

**Proof checklist while recording:** docs link card · "Last time you…" line · rising prices · two wallets moving independently · `budget_exceeded` notice · failing → passing test table · `fallback: yes` · `guardrail_violation` notice · teacher page + dashboard budget · `/status` all green.
