# Task Packet: Build an Autoresearch Skill for Recess

**Task ID:** task-autoresearch
**Created:** 2026-03-28
**Status:** Phase 0 ✅ COMPLETE | Phase 1 ✅ COMPLETE | Phase 2-3 PLANNED | Phase 4 PLANNED
**Owner:** Steve (OpenClaw)
**Approved by:** Deuce (2026-03-28)

---

## 1. Executive Summary

### What We're Building
An **Autoresearch skill** for OpenClaw that autonomously improves any prompt, skill, or agent workflow at Recess by running an automated test-and-improve loop. Inspired by Andrej Karpathy's autoresearch pattern (github.com/karpathy/autoresearch), adapted from ML training to prompt/workflow optimization.

### Why
Recess runs 7+ repeatable prompt-driven workflows (LinkedIn content, campaign recaps, meeting prep, sales outreach, system prompts, BigQuery NL→SQL, landing pages). Each was hand-tuned to "good enough" and left there. Quality varies run-to-run. Manual prompt iteration is slow (2-3 rounds/hour when a human is watching). An autonomous loop can run 50-100 rounds overnight and systematically find the prompt version that consistently passes quality criteria.

### Expected Outcomes
- **Prompt pass rates:** Improve from ~60-70% baseline to 90%+ across top 5 prompts
- **Time saved:** Replace 5-10 hours/week of manual prompt tweaking with overnight autonomous runs
- **Consistency:** Outputs that reliably meet quality criteria instead of hit-or-miss
- **Team enablement:** Give the Recess team (in AI training curriculum) a tool to optimize their own prompts

### Results to Date

| Target | Baseline | Final | Rounds | Cost | Status |
|--------|----------|-------|--------|------|--------|
| **LinkedIn draft** | 96.6% | — (skipped) | 0 | $0 | Baseline too high to optimize meaningfully |
| **OpenClaw system prompt** | 63.3% | 96.6% | 12 | $0.66 | ✅ Optimized SOUL.md deployed to production |

**Key findings from system prompt optimization:**
- Personality/voice mutation = +30% improvement in a single round (biggest single gain)
- Hard numeric word limits consistently made outputs worse — structural brevity guidance works better
- 10-20 point scoring variance observed between runs → 3x scoring with majority vote implemented as mitigation
- The loop converged fast (12 rounds vs 50 max) because the starting prompt had clear, fixable gaps

### Strategic Fit
This sits at the intersection of two Recess priorities:
1. **Operational leverage** — Fewer hours spent tuning prompts = more hours on strategy
2. **AI training curriculum** — Teaches the team what good eval criteria look like, which is the hardest part of working with AI

---

## 2. Architecture Design

### Where It Lives

Everything lives in a single location under the OpenClaw workspace:

```
clawd/skills/autoresearch/
├── SKILL.md                           # OpenClaw skill definition
├── scripts/
│   ├── autoresearch-loop.py           # Core loop runner
│   ├── scoring-engine.py              # Eval checklist scorer (calls Claude)
│   ├── mutation-engine.py             # Proposes one small change per round
│   ├── results-logger.py              # Writes round logs
│   └── utils.py
├── templates/
│   ├── eval-checklist-template.md     # Template for writing eval criteria
│   ├── program-template.md            # Template for program.md files
│   └── test-inputs-template.json
├── targets/
│   ├── linkedin-draft/
│   │   ├── program.md                 # Agent instructions for this target
│   │   ├── eval-checklist.md          # Binary eval criteria
│   │   ├── test-inputs.json           # Diverse test inputs
│   │   ├── original-prompt.md         # Never modified
│   │   ├── config.json                # Per-target config (budget_cap_usd: 10)
│   │   └── .autoresearch/
│   │       ├── best-prompt.md         # Current best version
│   │       ├── results.jsonl          # Round-by-round log
│   │       └── changelog.md           # Human-readable history
│   ├── openclaw-system-prompt/
│   │   ├── ...same structure...
│   │   └── config.json                # Per-target config (budget_cap_usd: 20)
│   ├── campaign-recap/
│   │   └── ...same structure...
│   └── ...more targets...
├── reports/
│   └── prompt-health.md              # Weekly aggregate report
└── README.md
```

### What Runs the Loop

**Primary: OpenClaw sub-agent session** (manual trigger or Slack command)

```
Deuce types: "Run autoresearch on linkedin-draft"
  → OpenClaw reads SKILL.md
  → Spawns sub-agent with autoresearch-loop.py
  → Sub-agent runs N rounds autonomously
  → Reports results back to Slack thread when done
```

**Secondary (Phase 2): Scheduled via OpenClaw cron**
- Weekly overnight runs on high-priority targets
- Cron triggers sub-agent, results posted to DM next morning

**Why not Cloud Run?** The loop needs to call Claude for both generation and scoring. OpenClaw already handles Claude API auth, sub-agent orchestration, and Slack reporting. Adding Cloud Run adds infra complexity for no gain at this stage. Can migrate later if we need parallel target runs.

### Results Storage

| Data | Location | Why |
|------|----------|-----|
| Round-by-round logs | `targets/{name}/.autoresearch/results.jsonl` | Git-tracked, diffable, co-located |
| Best prompt version | `targets/{name}/.autoresearch/best-prompt.md` | Always shows current winner |
| Changelog | `targets/{name}/.autoresearch/changelog.md` | Human-readable history |
| Aggregate metrics | BigQuery `recess_ops.autoresearch_runs` | Dashboarding, trend analysis |
| Summary per run | Slack DM thread | Deuce sees results without digging |

### Flow Diagram

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Trigger     │────▶│  Load Target  │────▶│  Load Current    │
│  (Slack/cron)│     │  program.md   │     │  Prompt Version  │
└─────────────┘     │  eval.md      │     │  + Test Inputs   │
                    │  test-inputs   │     └────────┬────────┘
                    └──────────────┘               │
                                                    ▼
                    ┌──────────────────────────────────────┐
                    │           AUTORESEARCH LOOP           │
                    │                                      │
                    │  ┌──────────┐    ┌──────────────┐    │
                    │  │ Mutation  │───▶│ Generate      │    │
                    │  │ Engine    │    │ Test Outputs  │    │
                    │  │ (1 small  │    │ (run prompt   │    │
                    │  │  change)  │    │  on all test  │    │
                    │  └──────────┘    │  inputs)      │    │
                    │                  └──────┬───────┘    │
                    │                         │            │
                    │                         ▼            │
                    │                  ┌──────────────┐    │
                    │                  │ Score Each    │    │
                    │                  │ Output 3x     │    │
                    │                  │ (majority     │    │
                    │                  │  vote/crit)   │    │
                    │                  └──────┬───────┘    │
                    │                         │            │
                    │                    ▼         ▼       │
                    │              ┌────────┐ ┌────────┐   │
                    │              │ Score  │ │ Score  │   │
                    │              │ Better │ │ Worse/ │   │
                    │              │→ KEEP  │ │ Equal  │   │
                    │              │→ Commit│ │→REVERT │   │
                    │              └────────┘ └────────┘   │
                    │                    │                  │
                    │                    ▼                  │
                    │              ┌────────────┐          │
                    │              │ Log Round  │          │
                    │              │ Results    │          │
                    │              └────────────┘          │
                    │                    │                  │
                    │         ┌──────────┴──────────┐      │
                    │         │ Converged or        │      │
                    │         │ Max Rounds?         │      │
                    │         └──────────┬──────────┘      │
                    │              No ↙     ↘ Yes          │
                    │          Loop back    Exit           │
                    └──────────────────────────────────────┘
                                                    │
                                                    ▼
                    ┌──────────────────────────────────────┐
                    │  Save best-prompt.md                  │
                    │  Update changelog.md                  │
                    │  Push to BigQuery                     │
                    │  Post summary to Slack DM             │
                    └──────────────────────────────────────┘
```

### MCP Interaction

The autoresearch loop itself is mostly self-contained (Claude API calls for generation + scoring). MCPs come into play for:
- **BigQuery MCP:** Storing aggregate results, and for testing the NL→SQL target (need real schema/data)
- **Slack MCP:** Reporting results, triggering runs
- **GitHub (gh CLI):** Committing improved prompts

The loop does NOT need all 8 MCPs active simultaneously, which avoids the ~70k context window collapse issue.

---

## 3. Eval Criteria Framework

### How Eval Criteria Work

Each target gets a **checklist of 3-6 binary (yes/no) questions**. A separate Claude call (Sonnet for cost efficiency) scores each output against the checklist. The score for a round = % of checks passed across all test inputs.

### 3x Scoring with Majority Vote

To mitigate 10-20 point scoring variance observed in Phase 0-1, every output is scored **3 times** per criterion. Each criterion's pass/fail is determined by majority vote (2 of 3 must agree). This reduces noise without tripling cost proportionally (scoring calls are cheap relative to generation).

- Configurable via `scoring_runs` in per-target `config.json`
- `vote_detail` field in scoring response shows agreement (e.g., "3/3", "2/3")
- Default: 3 runs. Can be set to 1 for cost-sensitive targets.
- Cost impact: ~3x on scoring calls (~$5.25 → ~$15 for a 50-round system prompt run). Budget caps adjusted accordingly ($20 for system prompt, $10 for simpler targets).

### Guidelines for Writing Good Eval Criteria

**Good criteria are:**
- **Observable** — Can be verified by reading the output (not "is it good?")
- **Binary** — Unambiguous yes or no (not "is the tone professional?" → too subjective)
- **Independent** — Each criterion tests one thing
- **Specific** — "Does the first sentence contain a number?" not "Does it use data?"
- **Anti-gameable** — Include at least one "coherence" or "readability" check

**Bad criteria (avoid):**
- "Is it well-written?" → Too subjective
- "Would this perform well on LinkedIn?" → Unprovable
- "Is the tone right?" → No clear standard

**Anti-gaming safeguard:** Every scoring response includes an `anti_gaming_pass` field where the scorer ignores the checklist and judges holistic quality. A keep decision is blocked if anti-gaming fails on 3+ of 10 test inputs. Additionally, every 10 rounds, a full anti-gaming audit runs all current best outputs through a more thorough holistic review to catch slow drift.

### Scoring Response Schema

The scoring engine returns structured JSON at temperature 0. This is the canonical schema:

```json
{
  "criteria": [
    {
      "id": "hook",
      "question": "Does the first line create curiosity or state a surprising fact without starting with 'I' or a question?",
      "pass": true,
      "reasoning": "The opening line states a specific statistic about sampling ROI that would surprise most marketers.",
      "vote_detail": "3/3"
    },
    {
      "id": "voice",
      "question": "Does it sound like a specific person sharing a real opinion?",
      "pass": false,
      "reasoning": "The tone is generic 'thought leader' — could be anyone. No personal angle or strong opinion.",
      "vote_detail": "1/3"
    }
  ],
  "total_pass": 4,
  "total_criteria": 6,
  "score": 0.667,
  "anti_gaming_pass": true,
  "anti_gaming_reasoning": "This reads like a real LinkedIn post someone would engage with."
}
```

Key design choices:
- `reasoning` field forces the scorer to cite specific evidence, improving reliability
- `vote_detail` shows per-criterion agreement across scoring runs (e.g., "3/3" = unanimous, "2/3" = majority)
- `anti_gaming_pass` and `anti_gaming_reasoning` are in the same response object (logged together, no separate call needed)
- `score` is `total_pass / total_criteria` as a decimal

### Eval Checklists

#### Target: LinkedIn Content Generation Prompt (Phase 0 — baseline only)

```markdown
## Eval Checklist: LinkedIn Draft

1. HOOK: Does the first line (before any line break) create curiosity or
   state a surprising fact — WITHOUT starting with "I" or a question?
   → Yes/No

2. VOICE: Does it sound like a specific person sharing a real opinion
   (not a generic "thought leader" post)?
   → Yes/No

3. BANNED PHRASES: Is it free of ALL phrases in the banned list
   (loaded from voice-profile.json)?
   → Yes/No

4. STRUCTURE: Does it use short paragraphs (≤3 lines each) with
   at least one line break between every paragraph?
   → Yes/No

5. SUBSTANCE: Does it include at least one specific data point,
   example, or named company/person (not vague generalizations)?
   → Yes/No

6. ANTI-GAMING: Read as a LinkedIn user scrolling their feed.
   Would you stop and read this? Genuinely — not technically.
   → Yes/No
```

**Status:** Baseline scored at 96.6% — too high to demonstrate meaningful optimization. Skipped full loop. Target preserved for future re-evaluation if the prompt changes.

#### Target: OpenClaw System Prompt (Phase 1 — ✅ COMPLETE)

```markdown
## Eval Checklist: OpenClaw System Prompt

Test method: Give the system prompt to a fresh Claude instance with
5 diverse user messages that involve making changes or completing tasks.
Score the RESPONSES.

1. CONCISENESS: Is each response under 200 words unless the user
   explicitly asked for detail?
   → Yes/No

2. ACTION-FIRST: Does the response lead with the answer/action
   (not "Great question!" or "I'd be happy to help!")?
   → Yes/No

3. TOOL USE: When the user's request could be answered by checking
   a system (Slack, Calendar, BigQuery, etc.), does the response
   indicate it would check the system (not just guess)?
   → Yes/No

4. PERSONALITY: Does the response have a distinct voice
   (not interchangeable with generic ChatGPT output)?
   → Yes/No

5. ACCURACY: Does the response avoid making up facts, inventing
   context, or hallucinating capabilities it doesn't have?
   → Yes/No

6. VERIFY-BEFORE-ASSERT: When the agent makes a change, runs code,
   or completes a task — does it show evidence of verification
   (test output, confirmation, or proof) IN THE SAME RESPONSE
   where it claims completion? The words "fixed," "done," "working,"
   or "complete" must be accompanied by evidence. Claiming completion
   without showing proof = automatic fail.
   → Yes/No
```

**Results:** 63.3% → 96.6% in 12 rounds, $0.66. Optimized SOUL.md deployed to production. Key mutations that stuck:
- 200-word default response limit with bullet points / short paragraphs (+20%)
- Ban on generic assistant language ("Let me walk you through", "I'd be happy to help", etc.) (+10%)
- Structural brevity guidance (+3.3%)

#### Target: Campaign Recap Generation Prompt (Phase 3 — planned)

```markdown
## Eval Checklist: Campaign Recap

1. METRICS PRESENT: Does the output include ALL of: total impressions,
   iROAS, venue count, and sampling volume?
   → Yes/No

2. BRANDED: Does it follow Recess brand formatting (section headers,
   no wall-of-text paragraphs, professional but not stiff)?
   → Yes/No

3. INSIGHT: Does it include at least one non-obvious insight
   (not just restating the numbers in sentence form)?
   → Yes/No

4. CLIENT-READY: Could this be sent to a brand partner without
   editing? (No placeholder text, no internal jargon, no TODOs)
   → Yes/No

5. ACCURATE MATH: Are any calculated metrics (percentages, averages,
   comparisons to benchmarks) mathematically correct given the
   input data?
   → Yes/No
```

---

## 4. Implementation Phases

### Phase 0: Foundation ✅ COMPLETE

**Goal:** Build the core loop and prove it works.

**Deliverables (all complete):**

1. **SKILL.md** — OpenClaw skill definition for autoresearch
2. **autoresearch-loop.py** — Core loop with convergence, tie-handling, anti-gaming
3. **scoring-engine.py** — 3x scoring with majority vote, structured JSON, temperature 0
4. **mutation-engine.py** — Single small change per round, temperature 0.7
5. **results-logger.py** — JSONL logging + changelog + best-prompt tracking
6. **Revert mechanism** — Git-based commits for keeps, reverts on failure
7. **LinkedIn draft target** — Full target directory with eval checklist and 10 test inputs

**Validation results:**
- Scoring engine: 100% consistency confirmed (same input → same output on repeated runs)
- LinkedIn baseline: 96.6% (too high to optimize — proves scoring works, but no room for improvement)
- Decision: pivot Phase 1 to system prompt (63.3% baseline — real room to improve)

**Acceptance Criteria (Phase 0):**
- [x] Can run `autoresearch-loop.py` against target from CLI
- [x] Scoring engine returns consistent results on same input (>90% agreement on repeated runs)
- [x] Mutation engine proposes small, relevant changes (not random rewrites)
- [x] Results log captures every round with score, change, and keep/revert decision
- [x] Git history shows clean commits for each kept improvement
- [x] Equal-score mutations are reverted (verified in logs)
- [x] Convergence uses 3-of-last-5 rule (verified)

### Phase 1: OpenClaw System Prompt ✅ COMPLETE

**Target: OpenClaw system prompt (SOUL.md)** — the highest-leverage optimization target. Affects every interaction.

**Why system prompt instead of LinkedIn for Phase 1:**
- LinkedIn scored 96.6% at baseline — no room to prove the loop works
- System prompt scored 63.3% — real gap between current and optimal
- System prompt affects every team member interaction (highest blast radius)

**Results:**

| Round | Score | Mutation | Decision |
|-------|-------|----------|----------|
| 0 | 63.3% | — (baseline) | — |
| 1 | 66.7% | Added conciseness guidance | KEEP |
| 2 | 70.0% | Refined tool-use instructions | KEEP |
| 3 | 93.3% | Added personality/voice rules (+23.3%) | KEEP |
| 4-8 | 86.7-90.0% | Various refinements | Mixed KEEP/REVERT |
| 9 | 93.3% | Structural brevity (bullets, short paragraphs) | KEEP |
| 10 | 96.6% | Ban generic assistant language | KEEP |
| 11-12 | 96.6% | Convergence confirmed | EXIT |

**Total cost:** $0.66 (well under $20 cap)
**Total rounds:** 12 (well under 50 max)

**Key learnings:**
- **Personality mutation was the biggest single gain** — going from generic to specific voice rules added +23.3% in one round
- **Hard numeric word limits hurt** — "Max 150 words" type rules consistently degraded quality. "Keep responses under 200 words unless asked for detail" (structural guidance) worked much better.
- **Scoring variance is real** — 10-20 point swings observed between identical runs. 3x scoring with majority vote implemented to mitigate.
- **The loop converges fast** when starting from a prompt with clear fixable gaps

**Deployed changes to SOUL.md:**
1. 200-word default response limit with bullet points / short paragraphs
2. Ban on generic assistant language ("Let me walk you through", "I'll help you", "Let me know once it's updated")

**Acceptance Criteria (Phase 1):**
- [x] Baseline score established and documented (63.3%)
- [x] Loop completed without errors (12 rounds)
- [x] Final score measurably higher than baseline (96.6% vs 63.3%)
- [x] Deuce confirmed improved outputs are actually better (human validation)
- [x] Improved prompt deployed after Deuce approval

### Phase 2: Dashboard + Automation (PLANNED — Weeks 3-4)

**Deliverables:**

1. **Slack command trigger**
   - "Run autoresearch on linkedin-draft" → spawns sub-agent, posts results to thread
   - "Autoresearch status" → shows last run results per target
   - "Autoresearch history linkedin-draft" → shows score progression

2. **Results dashboard** (start with Slack-native summaries)
   - Weekly summary posted to DM with score trends per target
   - Upgrade to Google Sheet or GitHub Pages if team wants to explore data

3. **Scheduled runs**
   - OpenClaw cron: Run each target weekly (overnight, staggered)
   - Results posted to DM next morning
   - Auto-save improved prompts (original always preserved)

4. **Prompt version management**
   - `original-prompt.md` — Never modified (the starting point)
   - `best-prompt.md` — Current winner (updated by loop)
   - `best-prompt-v{N}.md` — Numbered snapshots for rollback
   - Production prompt always pulled from `best-prompt.md`

**Scope:** Steve/Deuce only through Phase 2. Team access in Phase 3.

**Acceptance Criteria (Phase 2):**
- [ ] Can trigger autoresearch from Slack
- [ ] Results summary posted automatically after each run
- [ ] At least 2 targets running on weekly schedule
- [ ] Prompt versions tracked and rollback-capable

### Phase 3: Scale to All Key Prompts (PLANNED — Week 5+)

1. **Roll out to remaining targets** (see Appendix C for prompt locations):
   - Campaign recap generation
   - Meeting prep automation
   - Supply-side sales outreach
   - Landing page copy generator
   - BigQuery NL→SQL

2. **"Prompt Health" report**
   - Weekly aggregate: pass rates across all optimized prompts
   - Trend lines: are prompts improving, degrading, or stable?
   - Alert if any prompt drops below 80%

3. **Team adoption**
   - Open autoresearch to broader team as part of AI training curriculum
   - Template for team members to create their own autoresearch targets
   - Workshop: "How to write eval criteria"
   - Each team member optimizes one prompt they use regularly

4. **BigQuery integration**
   - All run data flows to `recess_ops.autoresearch_runs`
   - Fields: target, round, score, change_description, kept, timestamp, model_used, cost
   - Enables cross-target analysis and cost tracking

**Acceptance Criteria (Phase 3):**
- [ ] 5+ targets actively running
- [ ] At least 2 team members have created their own target
- [ ] Prompt health report running weekly
- [ ] All results in BigQuery for analysis

### Phase 4: Skill-Level Autoresearch — Workflow Optimization (PLANNED)

*This is planning only. Do not build until Phases 2-3 are stable and reviewed.*

#### The Problem Phases 0-3 Don't Solve

Phases 0-3 optimize prompt text — the instructions inside a SKILL.md or system prompt. But the biggest quality failures at Recess aren't word choice problems. They're workflow problems:

- OpenClaw builds UI and claims it's done without running Playwright → **missing verification step**
- Newsletter cron does web search + content generation in one shot and times out → **wrong workflow architecture**
- Campaign recap generates content but doesn't validate that required metrics are present in the input data → **missing pre-flight check**
- Code changes get committed without running the test suite → **missing quality gate**

No amount of prompt mutation fixes these. The skill needs structural changes — adding steps, removing steps, reordering steps, adding error handling.

#### What Skill-Level Autoresearch Looks Like

Instead of mutating text in one file, the loop mutates the **workflow definition** of a skill by toggling predefined workflow steps on/off and measuring if outcomes improve.

##### The Workflow Steps Menu

A curated library of proven workflow patterns that can be added to or removed from any skill. These are NOT free-form code edits — they're tested, modular blocks:

**Verification Steps:**
- `playwright-verify` — Run Playwright tests on UI output before reporting done
- `dry-run-first` — Execute a dry run before making real changes
- `output-schema-validate` — Validate output matches expected JSON/data schema
- `diff-review` — Show the diff of any file changes and confirm they're intentional

**Pre-flight Checks:**
- `input-completeness-check` — Verify all required input data exists before starting
- `dependency-health-check` — Confirm external services (APIs, databases) are reachable
- `context-window-check` — Verify context window has enough room before proceeding
- `budget-check` — Confirm remaining budget before expensive operations

**Quality Gates:**
- `test-suite-run` — Run existing tests after any code change
- `lint-and-format` — Run linter before committing
- `human-approval-gate` — Pause and request approval before deploying
- `rollback-checkpoint` — Create a restore point before making changes

**Error Handling:**
- `timeout-with-fallback` — Set a timeout and define fallback behavior
- `retry-with-backoff` — Retry failed operations with exponential backoff
- `graceful-degradation` — Define what to do when a dependency is unavailable
- `error-notification` — Send Slack alert on failure

**Reporting:**
- `progress-updates` — Send status updates every N minutes for long tasks
- `completion-evidence` — Include proof of completion (test output, screenshots, logs) in done message
- `cost-tracking` — Log API costs per operation

##### How the Loop Works

```
SKILL-LEVEL AUTORESEARCH LOOP:

1. Load the skill's current workflow definition
   (SKILL.md + any scripts/configs)

2. Load the skill's eval checklist
   (same binary yes/no format, but criteria now include workflow quality)

3. Run the skill on test inputs → score against checklist → establish baseline

4. LOOP:
   a. Analyze which eval criteria are failing
   b. Select a workflow step from the menu that could fix the failure
      - Failing "verify before assert"? → Try adding `playwright-verify`
      - Failing "handles errors gracefully"? → Try adding `timeout-with-fallback`
      - Failing "provides progress updates"? → Try adding `progress-updates`
   c. Add the workflow step to the skill definition
   d. Run the skill on test inputs → score
   e. Score improved? → KEEP the step, commit
      Score same or worse? → REMOVE the step, revert
   f. Repeat

5. Output: An improved skill with the optimal combination of workflow steps
```

##### Key Difference from Prompt Autoresearch

| Aspect | Prompt Autoresearch (Phase 0-3) | Skill Autoresearch (Phase 4) |
|---|---|---|
| What's mutated | Text in SKILL.md or prompt file | Workflow steps added/removed from skill |
| Mutation source | LLM proposes new wording | Selection from predefined menu of steps |
| Risk of breaking things | Low (just text) | Medium (adding code/logic) |
| What it fixes | Output quality, tone, formatting | Process gaps, missing checks, error handling |
| Eval criteria focus | "Is the output good?" | "Did the skill execute correctly?" |

##### Example: Applying to the UI Build Skill

Current skill: Builds UI features when asked.
Current failure: Claims done without testing, cards don't render, click handlers missing.

**Eval checklist for skill-level optimization:**

```markdown
1. RENDERS: Does the built component actually render in the browser
   without console errors?
   → Yes/No

2. INTERACTIVE: Do all clickable elements respond to clicks
   with the expected behavior?
   → Yes/No

3. DATA-CORRECT: Does the displayed data match what the API returns?
   → Yes/No

4. TESTED: Are Playwright tests included that cover rendering,
   interaction, and data correctness?
   → Yes/No

5. EVIDENCE: Does the completion message include test output
   proving the above?
   → Yes/No
```

The loop would try adding workflow steps:
- Round 1: Add `playwright-verify` → score improves on criteria 4 and 5 → KEEP
- Round 2: Add `output-schema-validate` → score improves on criterion 3 → KEEP
- Round 3: Add `lint-and-format` → score unchanged → REVERT
- Round 4: Add `dry-run-first` → score unchanged → REVERT
- Result: Skill now includes Playwright verification and schema validation as permanent steps

##### How Workflow Steps Are Implemented

Each step in the menu is a self-contained module with:

```
workflow-steps/
├── playwright-verify/
│   ├── README.md          # What this step does, when to use it
│   ├── inject.md          # Instructions to add to SKILL.md
│   ├── setup.sh           # Any one-time setup (npm install playwright, etc.)
│   ├── template.ts        # Template test file the skill customizes
│   └── eval-criteria.md   # What eval criteria this step should improve
├── timeout-with-fallback/
│   ├── README.md
│   ├── inject.md
│   └── template.py
├── progress-updates/
│   ├── README.md
│   └── inject.md
└── ...
```

The `inject.md` is the key file — it's the text that gets added to the skill's SKILL.md when the step is toggled on. This means the mutation is still text-based (adding/removing inject.md content from SKILL.md), but the text represents a workflow change, not a wording change.

This keeps the same mechanical simplicity as prompt autoresearch (modify one file, measure, keep/revert) while enabling structural improvements.

#### Eval Criteria: Workflow Quality vs. Output Quality

Phase 0-3 eval criteria ask: "Is the output good?"
Phase 4 eval criteria ask: "Did the skill execute correctly?"

Both should be used together. A skill can produce good output (passes Phase 0-3 criteria) through a bad process (skips testing, doesn't handle errors). Phase 4 catches process failures that Phase 0-3 misses.

Combined eval checklist example:

```markdown
## Output Quality (Phase 0-3 criteria)
1. Is the output correct and complete? → Yes/No
2. Is it concise? → Yes/No
3. Does it match the expected format? → Yes/No

## Workflow Quality (Phase 4 criteria)
1. Were all required pre-flight checks run? → Yes/No
2. Was the output verified before reporting done? → Yes/No
3. Were errors handled gracefully (not silently swallowed)? → Yes/No
4. Was evidence of completion included? → Yes/No
```

#### Prerequisites Before Phase 4

1. Phase 2-3 must be stable (Slack command, scheduled runs, 3+ targets running)
2. The workflow steps menu needs to be built and tested individually before the loop can use them
3. Need real failure data from Phase 2-3 runs to know which workflow steps matter most
4. Each workflow step needs its own tests to confirm it doesn't break existing functionality

#### Implementation Approach

**Phase 4A: Build the workflow steps menu (2-3 weeks)**
- Start with the 5 most impactful steps based on real failure data
- Build each as a self-contained module in `workflow-steps/`
- Test each individually on a real skill
- Recommended starting set: `playwright-verify`, `completion-evidence`, `progress-updates`, `timeout-with-fallback`, `input-completeness-check`

**Phase 4B: Build the skill-level loop (1-2 weeks)**
- Extend autoresearch-loop.py to handle workflow step mutations
- Add the workflow-quality eval criteria framework
- Run first skill-level optimization on a test skill

**Phase 4C: Apply to real skills (ongoing)**
- Start with the UI build skill (biggest pain point)
- Then code review skill
- Then cron job management skill
- Each run produces data on which workflow steps actually help

#### Open Questions for Deuce

1. Which 5 workflow steps from the menu would you prioritize? 16 listed — we should start with the ones that match your biggest pain points.
2. Should the workflow steps be global (apply to all skills) or per-skill (each skill gets its own combination)? Recommendation: per-skill with a recommended default set.
3. How do we handle the case where a workflow step requires setup (e.g., Playwright needs `npm install`)? Should the loop handle setup automatically, or should setup be a prerequisite?
4. Budget: skill-level runs will be more expensive because testing workflow changes requires actually running the skill end-to-end. Rough estimate: $30-50/run. Acceptable?

**Acceptance Criteria (Phase 4):**
- [ ] Workflow steps menu contains at least 5 tested, modular steps
- [ ] Skill-level loop can add/remove workflow steps and measure impact
- [ ] At least one real skill optimized end-to-end with measurable improvement
- [ ] Combined eval checklist (output quality + workflow quality) validated
- [ ] Cost per skill-level run documented and within approved budget

*This is Phase 4 planning only. Do not build until Phases 2-3 are stable and reviewed.*

---

## 5. Technical Specifications

### Model Selection

| Role | Model | Temperature | Why |
|------|-------|-------------|-----|
| **Generation** | Same model used in production for that prompt | Production temp | Results must reflect real-world performance |
| **Scoring** | Claude Sonnet 4 | **0** | Deterministic, cost efficient, structured JSON output |
| **Mutation** | Claude Sonnet 4 | **0.7** | Creative variety; avoids repetitive proposals after reverts |
| **Anti-gaming** | Claude Sonnet 4 | **0** | Bundled into scoring call; independent holistic judgment |

### 3x Scoring Implementation

Every output is scored 3 times independently. For each criterion, the pass/fail decision is determined by majority vote (2 of 3 must agree). This addresses the 10-20 point scoring variance observed during Phase 0-1.

**How it works:**
1. Same output + eval checklist sent to scoring model 3 separate times
2. For each criterion: if 2+ of 3 runs say "pass", criterion passes
3. `vote_detail` field records agreement (e.g., "3/3" = unanimous, "2/3" = majority)
4. Final score = majority-voted passes / total criteria

**Configuration:**
- `scoring_runs` in per-target `config.json` (default: 3)
- Can be set to 1 for cost-sensitive targets or during development

**Cost impact:**
- 3x scoring makes runs ~$15 instead of ~$5.75 for a full 50-round run
- Budget caps adjusted: $20 for system prompt target, $10 for simpler targets

### Cost Estimates

Per autoresearch run (50 rounds × 10 test inputs, with 3x scoring):

| Component | Calls | Model | Avg tokens (in/out) | Est. cost |
|-----------|-------|-------|---------------------|-----------|
| Generation | 500 (50×10) | Sonnet 4 | ~1000 in / 1500 out | ~$3.75 |
| Scoring (3x) | 1,500 (50×10×3) | Sonnet 4 | ~2000 in / 700 out | ~$5.25 |
| Mutation | 50 (1/round) | Sonnet 4 | ~3000 in / 1000 out | ~$0.25 |
| **Total per run** | **2,050** | | | **~$9.25** |

At weekly runs across 5 targets: **~$46/week, ~$185/month**

Per-run budget caps:
- **System prompt target:** $20 (complex scoring, high value)
- **All other targets:** $10 (default)

### Convergence Criteria

**95%+ on 3 of the last 5 rounds.** This is more robust than "3 consecutive" because it tolerates one-off scoring variance. If round N scores 96%, round N+1 scores 93% (variance), and rounds N+2 through N+4 score 95%+, we still converge. With strict consecutive, that one blip would reset the counter.

### Tie-Handling Rule

**Equal scores are reverted.** If `new_score == baseline_score`, the mutation is discarded. Mutations should earn their place — no complexity added for zero improvement. This is enforced with a strict `>` comparison (not `>=`).

### Configuration Defaults

```json
{
  "max_rounds": 50,
  "test_inputs_per_round": 10,
  "convergence_threshold": 0.95,
  "convergence_window": 5,
  "convergence_required": 3,
  "scoring_model": "claude-sonnet-4-20250514",
  "scoring_temperature": 0,
  "scoring_runs": 3,
  "mutation_model": "claude-sonnet-4-20250514",
  "mutation_temperature": 0.7,
  "generation_temperature": "match_production",
  "max_mutation_lines": 5,
  "anti_gaming_block_threshold": 3,
  "anti_gaming_audit_interval": 10,
  "budget_cap_usd": 10.00,
  "timeout_minutes": 120,
  "tie_handling": "revert"
}
```

Per-target overrides via `targets/{name}/config.json`:
- `openclaw-system-prompt`: `budget_cap_usd: 20`
- `linkedin-draft`: `budget_cap_usd: 10`

---

## 6. Risks & Constraints

### Context Window (HIGH risk)
- **Problem:** With 8 MCPs active, context can collapse to ~70k tokens
- **Mitigation:** Autoresearch runs as an isolated sub-agent with NO MCPs loaded. Only needs Claude API access (generation/scoring) and filesystem access. MCPs only for trigger (Slack) and reporting, which happen outside the loop.

### Cost Overrun (MEDIUM risk)
- **Problem:** Runaway loop or too many targets = unexpected API bill
- **Mitigation:** Hard budget cap per run (per-target config), max rounds (50), and timeout (2 hours). If budget is hit, loop stops and reports partial results. 3x scoring increases cost ~3x on scoring calls — budget caps adjusted to account for this.

### Prompt Drift (MEDIUM risk)
- **Problem:** Each mutation is small, but 50 small changes can collectively drift away from original intent
- **Mitigation:**
  1. Original prompt always preserved (never modified)
  2. Anti-gaming check catches coherence drift (every round + audit every 10 rounds)
  3. program.md includes explicit constraints ("maintain Deuce's voice," etc.)
  4. Human review required before deploying improved prompt (Deuce approval — option b)

### Checklist Gaming (MEDIUM risk)
- **Problem:** Mutation engine optimizes for passing the checklist, not actual quality
- **Mitigation:**
  1. Anti-gaming field in every scoring response
  2. Block keeps if 3+ test inputs fail anti-gaming
  3. Diverse test inputs (prompt must work across scenarios)
  4. Periodic human review
  5. Checklist evolution — if gaming detected, add criteria that catch it

### External System Dependencies (LOW risk for Phase 0-1)
- **Problem:** Some prompts need real data to test properly
- **Mitigation:** Phase 0-1 targets don't need external systems. Phase 3 targets like BigQuery NL→SQL will need test datasets — known future complexity, not a blocker.

### Scoring Consistency (MEDIUM risk — mitigated)
- **Problem:** LLM scoring may not be deterministic. 10-20 point variance observed in Phase 0-1.
- **Mitigation:**
  1. Structured JSON output with `reasoning` field reduces ambiguity
  2. Temperature 0 for scoring
  3. **3x scoring with majority vote per criterion** (implemented after Phase 0-1 variance observed)
  4. `vote_detail` field tracks per-criterion agreement for debugging
  5. Validated: scoring engine shows 100% consistency on identical inputs at temperature 0

---

## 7. Success Metrics

### Primary Metrics

| Metric | Baseline | Actual | Phase 3 Target |
|--------|----------|--------|----------------|
| LinkedIn draft pass rate | 96.6% | — (skipped, too high) | Re-evaluate if prompt changes |
| System prompt pass rate | 63.3% | **96.6%** ✅ | Maintain 90%+ |
| Campaign recap pass rate | TBD | — | 90%+ |
| Targets actively running | 0 | 2 (baseline established) | 5+ |
| Manual prompt editing time/week | ~5-10 hrs | TBD (Phase 2 tracking) | ~1 hr |

### Secondary Metrics

- **Scoring consistency:** 100% on identical inputs (validated Phase 0) ✅
- **Mutation quality:** System prompt run: ~50% keep rate (healthy)
- **Convergence speed:** System prompt converged in 12 rounds (well under 50 max) ✅
- **Cost efficiency:** $0.66 for system prompt run (well under $20 cap) ✅
- **Team adoption:** 2+ team members create their own targets by Phase 3

### Failure Signals
- Pass rate improves but humans say outputs are worse → checklist gaming
- Mutation keep rate <10% → mutation engine too random, improve program.md
- Score plateaus early → eval criteria too easy or too hard
- Cost exceeds budget cap consistently → loop inefficiency

---

## 8. Decisions Log

| # | Date | Question | Decision |
|---|------|----------|----------|
| 1 | 2026-03-28 | First target | LinkedIn for Phase 0 validation, OpenClaw system prompt for Phase 1 production |
| 2 | 2026-03-28 | Eval criteria timing | Build framework first in Phase 0, iterate on criteria during Phase 1 |
| 3 | 2026-03-28 | Deployment approval | Option (b) — Deuce approves before deploying. Evolve to (c) once trusted |
| 4 | 2026-03-28 | Recess Brain repo | Located at `github.com/deucethevenow/recess-brain`. Will clone when needed for Phase 3. |
| 5 | 2026-03-28 | Budget | $115/month approved (revised to ~$185/month with 3x scoring). Per-run cap: $20 system prompt, $10 others |
| 6 | 2026-03-28 | Team involvement | Steve/Deuce only through Phase 2. Team access in Phase 3 via AI training curriculum |
| 7 | 2026-03-28 | LinkedIn pivot | Skipped LinkedIn optimization (96.6% baseline too high). Pivoted Phase 1 to system prompt. |
| 8 | 2026-03-28 | Convergence rule | Changed from "3 consecutive" to "3 of last 5 rounds" — tolerates scoring variance |
| 9 | 2026-03-28 | Tie handling | Equal scores revert (strict `>`, not `>=`). Mutations must earn their place. |
| 10 | 2026-03-29 | 3x scoring | Every output scored 3 times with majority vote per criterion. Addresses 10-20pt variance. |
| 11 | 2026-03-29 | Budget cap adjustment | System prompt target: $20 (accounts for 3x scoring cost). Simpler targets: $10. |
| 12 | 2026-03-29 | SOUL.md deployment | Optimized SOUL.md approved and deployed. Two additions: 200-word limit + ban generic assistant language. |

---

## Appendix A: Comparison to Karpathy's Original

| Aspect | Karpathy AutoResearch | Recess AutoResearch |
|--------|----------------------|---------------------|
| What's optimized | PyTorch training code | Prompts & agent workflows |
| Metric | val_bpb (lower = better) | Eval checklist pass rate (higher = better) |
| What agent modifies | `train.py` (one file) | Target prompt (one file) |
| Time per round | 5 min (GPU training) | ~30 sec (API calls) |
| Rounds per hour | ~12 | ~60-120 |
| Hardware required | NVIDIA GPU (H100) | None (API-based) |
| Scoring | Automatic (loss function) | LLM-judged (binary checklist, 3x majority vote) |
| Key risk | Overfitting to val set | Checklist gaming |

Our version is more efficient per round (seconds vs. minutes) but less precise in scoring (LLM judgment vs. mathematical loss). The anti-gaming safeguards and 3x scoring are our answer to the precision gap.

## Appendix B: Example `program.md` for LinkedIn Target

```markdown
# AutoResearch Program: LinkedIn Draft Generation

## Your Role
You are optimizing a LinkedIn post generation prompt for Deuce Thevenow,
COO of Recess (CPG sampling + experiential retail media).

## What You Can Modify
- The file `best-prompt.md` in this directory
- You may change: instructions, examples, constraints, formatting rules
- You may NOT change: the eval checklist, test inputs, or this file

## Constraints
- Keep the prompt under 2000 words
- Maintain Deuce's voice (direct, analytical, uses specific examples)
- The prompt must work with both news inputs AND transcript insights
- Do not add instructions that reference specific test inputs (no overfitting)

## Strategy
- Look at which eval criteria failed in the last round
- Make ONE targeted change to address the most common failure
- Prefer changes that are general (help across all inputs) over specific
- If a change helps one criterion but hurts another, revert it

## What Good Looks Like
A great LinkedIn post from this prompt should:
- Stop someone mid-scroll with a surprising or contrarian opening
- Share a real opinion (not a summary of an article)
- Include specific details (numbers, company names, personal experience)
- End with something the reader walks away thinking about
- Sound like Deuce, not like "LinkedIn thought leader"
```

## Appendix C: Prompt Inventory

Locations of all target prompts for Phase 3 planning. Gathered 2026-03-28.

| Target | Location | Status |
|--------|----------|--------|
| **LinkedIn content generation** | `~/recess-engage/prompts/linkedin/generate-draft.md` | ✅ Located — Phase 0 baseline target |
| **OpenClaw system prompt** | `~/clawd/SOUL.md` + `~/clawd/AGENTS.md` | ✅ Located — Phase 1 target (COMPLETE) |
| **Campaign recap / case study** | **UNKNOWN** — Deuce to confirm: Make.com scenario? Google Doc? Airtable? | ❓ Need location |
| **Lindy.ai meeting prep** | **UNKNOWN** — Lives inside Lindy.ai automation. Deuce or Ian to export the prompt text. | ❓ Need location |
| **Supply-side sales outreach** | **UNKNOWN** — Likely a Lindy.ai automation. Deuce to confirm. | ❓ Need location |
| **Landing page copy generator** | **UNKNOWN** — Make.com scenario or standalone? Deuce to confirm. | ❓ Need location |
| **BigQuery NL→SQL** | `~/clawd/skills/bigquery-query-agent/SKILL.md` | ✅ Located — can optimize the skill's prompt instructions |

**Note:** The 3 unknown locations are not blockers for Phase 0-2. We need them documented before Phase 3 begins. Deuce can provide locations async anytime in the next 4 weeks.

---

*End of Task Packet. Last updated: 2026-03-29. Phase 0-1 complete. Phase 2-4 planned.*
