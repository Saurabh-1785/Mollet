# Demo video script (target 4:30, hard limit 5:00)

Your own screen and your own voice; no AI voice or AI video. Read the lines below
once or twice, then say them **in your own words**: it sounds more natural and
the rules ask for your voice, not a reading. Say each **feature name** out loud
while it is on screen.

Record on the **deployed** app (https://mollet.onrender.com) with the real key,
never with `MOLLET_MOCK`.

---

## Part 1. Before you press record (15 min)

1. **Wait for Render to finish deploying** the latest commit. A redeploy wipes
   the database, which is what you want: clean wallets and history.
2. **Otari dashboard → Spend & budgets → `mollet-weekly-wallet`**: set
   `max_budget` to **$0.015** for the recording. A rung-1 hint costs about
   $0.01 (it includes a web search), so Asha runs dry after a few hints.
   Set it back to **$0.05** afterwards (it is $1.00 right now).
3. **Give Asha history for MCP to recall.** Open
   `https://mollet.onrender.com/learn/student_001/count-vowels`, paste the buggy
   code below and click **Run hidden tests** once (free; billed to the class):
   ```python
   def count_vowels(text):
       return sum(1 for c in text if c in "aeiou")
   ```
   Then clear the editor.
4. **Prepare the fallback shot.** In **Routing → Policies → `mollet-hinter`**,
   put a model first that your workspace cannot serve (or switch that model's
   provider off), ask Ben (student_002) for one hint on `fizzbuzz` and check the
   trace shows `fallback: yes`. Take a screenshot of the trace, then **restore
   the policy** (Qwen first, Mistral second). Doing this off camera keeps the
   recording short and safe; you show the trace and the policy on camera.
5. **Warm up**: open the app 1 minute before recording (Render's free plan sleeps).
6. **Tabs, in this order:**
   1. Mollet learn page: `/learn/student_001/count-vowels` (Asha)
   2. Mollet `/teacher`
   3. Mollet `/status`
   4. Otari dashboard: Routing → Policies
   5. Otari dashboard: Spend & budgets
   6. Otari dashboard: Organization → Guardrails
   7. Otari dashboard: Tools → MCP servers → `classroom`
   8. GitHub: repo on branch `otari-hackathon`
7. Browser zoom 110–125% so text is readable; close notifications.

Things to avoid on camera:
- Don't type a UK number like `+44 7700 900123`: Lakera lets it through. Use
  the exact phone sentence in the script.
- Don't ask a hint like "reply with one word OK": Lakera's prompt-injection
  check can flag commands like that.

---

## Part 2. The script

### 0:00–0:35 · The problem

**Show:** Mollet learn page, nothing clicked yet.

> Beginner programmers get stuck, and today the fix is one click away: paste the
> problem into a chatbot and copy the answer. The code works, but the student
> learned nothing. Teachers can't ban AI, and they can't afford to give every
> student an unlimited, expensive model either. So there are two problems:
> AI does the thinking for the student, and nobody controls what it costs.

### 0:35–1:05 · The idea and the solution

**Show:** point at the hint ladder and the wallet in the side panel.

> My idea: make help cost something, like in real life. Mollet is a hint wallet.
> Each student has a small weekly wallet of real money. Help comes as a five-rung
> ladder: Point, Explain, Approach, Sketch, Walk-through. Each rung gives a
> little more and costs a little more, and Mollet never gives the full answer.
> Students learn to ask for the smallest hint that unblocks them.
> Everything runs on Otari with open-weight models.

### 1:05–1:50 · Working: hints, web search, MCP, multiple models

**Show:** as Asha, click **Ask for a hint** (rung 1). Point at the docs link
card. Open **Otari trace**. Click again (rung 2), point at the line about her
earlier mistake. Open the trace, point at the MCP tool calls.

> Rung one names the concept and links the real Python docs. That link comes from
> Otari's built-in **web search**, capped at one search per hint. In the trace you
> can see the search and which model answered.
>
> Rung two remembers Asha's earlier mistake: she forgot upper-case vowels. That
> memory comes from my own **MCP server**, the classroom server, which Otari calls
> with two tools, get_problem and get_student_history.
>
> Mollet uses **multiple open-weight models**: Qwen 3 for the cheap rungs,
> DeepSeek V3.1 for the deeper rungs, and Qwen 3 Coder as the Grader.

### 1:50–2:30 · Working: per-user budgets

**Show:** Asha's wallet bar dropping. Click **Ask** again (rung 3), then switch
to `fizzbuzz` and ask until Otari refuses: **"Wallet empty · refills Monday."**
Switch student to Ben: his wallet is untouched.

> Every price is the real cost Otari billed for that hint. Each student is an
> Otari end user under one service key, so each one has their own budget:
> that's Otari's **per-user budgets**. Asha's wallet is empty, so Otari itself
> refuses the next hint. My app doesn't fake it. Ben's wallet hasn't moved.

### 2:30–3:10 · Working: code execution and the Grader

**Show:** back to Asha, paste the buggy code, **Run hidden tests** → 3/5 table
and feedback. Add `.lower()` → **Run hidden tests** → 5/5, **Solved** chip.

> Even with an empty wallet, Asha can still check her work. Her code runs against
> hidden tests in Otari's sandbox: that's **code execution**. The pass/fail
> table is real output, not a model's opinion. Then the Grader model reads those
> results and explains the bug without writing the fix. She adds one method call
> and every test passes.

### 3:10–3:45 · Feature: routing and fallbacks

**Show:** Otari dashboard, Routing → Policies (`mollet-hinter`, `mollet-mentor`),
then your screenshot of the trace with `fallback: yes`.

> Model choice is Otari **routing**. The Hinter policy is a fallback chain:
> Qwen first, Mistral Small if Qwen fails. Here I broke the first model, and the
> trace shows Mistral answered, with fallback yes. The Mentor policy tiers down
> to a cheaper model when the budget fills up. My app only asks for a policy
> name; Otari picks the model.

### 3:45–4:10 · Feature: guardrails

**Show:** switch to Chen (student_003). In the question box type
`My phone number is +1 415 555 0134, can you call me and explain?` → Ask →
**"Message blocked to keep you safe."** Briefly show Organization → Guardrails.

> These are kids, so personal data must never reach a model. An Otari
> **guardrail** in block mode stops this message before any provider sees it.
> Not giving the full answer is my own app rule: if a hint's code would pass the
> hidden tests, Mollet catches it and rewrites it.

### 4:10–4:30 · Feature: class budget and the teacher

**Show:** `/teacher` (wallets, independence scores, refusals list), then the
Otari Spend & budgets page with the workspace budget.

> The whole class sits under a workspace **budget** in Otari, so a teacher knows
> the most they can spend in a week. The teacher page shows each wallet and an
> independence score: problems solved with few or no hints.

### 4:30–4:45 · Close

**Show:** `/status` with the feature cards, then GitHub on branch `otari-hackathon`.

> Mollet: open-weight models only, and eight Otari features, from web search
> and MCP to budgets, routing, code execution and guardrails. Code is on GitHub,
> branch otari-hackathon. Thanks for watching.

---

## Part 3. Proof checklist (tick while recording)

- [ ] Docs link card on rung 1, trace shows `web_search`
- [ ] "You forgot upper-case…" style line on rung 2, trace shows `mcp` calls
- [ ] Three different models named (Qwen 3, DeepSeek V3.1, Qwen 3 Coder)
- [ ] Rising rung prices, wallet bar dropping
- [ ] "Wallet empty · refills Monday" for Asha, Ben's wallet unchanged
- [ ] Failing 3/5 table → fixed → 5/5 and **Solved**
- [ ] Routing policies on the dashboard + `fallback: yes` trace
- [ ] "Message blocked to keep you safe"
- [ ] Teacher page + workspace budget on the dashboard
- [ ] `/status` + repo URL and branch

## After recording

- Set `mollet-weekly-wallet` back to **$0.05**.
- Upload, set the video to **Public** or **Unlisted**, and open the link in a
  logged-out browser to check it plays.
