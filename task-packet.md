# Task Packet: Build an Autoresearch Skill for Recess

**Task ID:** task-autoresearch
**Created:** 2026-03-28
**Status:** Planned (pending review)
**Owner:** Steve (OpenClaw) → Deuce approval required

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

### Strategic Fit
This sits at the intersection of two Recess priorities:
1. **Operational leverage** — Fewer hours spent tuning prompts = more hours on strategy
2. **AI training curriculum** — Teaches the team what good eval criteria look like, which is the hardest part of working with AI

---

## 2. Architecture Design

### Where It Lives

```
clawd/skills/autoresearch/           ← The skill itself (SKILL.md + runner)
  SKILL.md                           ← OpenClaw skill definition
  scripts/
    autoresearch-loop.py             ← Core loop runner
    scoring-engine.py                ← Eval checklist scorer (calls Claude)
    mutation-engine.py               ← Proposes one small change per round
    results-logger.py                ← Writes round logs
  templates/
    eval-checklist-template.md       ← Template for writing eval criteria
    program-template.md              ← Template for program.md files

recess-brain/skills/autoresearch/    ← Results & configs per target
  targets/
    linkedin-draft/
      program.md                     ← Instructions for this target
      eval-checklist.md              ← Binary eval criteria
      test-inputs.json               ← Diverse test inputs
      .autoresearch/
        results.jsonl                ← Round-by-round log
        best-prompt.md               ← Current best version
        changelog.md                 ← Human-readable history
    campaign-recap/
      ...same structure...
    openclaw-system-prompt/
      ...same structure...
```

**Rationale:** The skill (how to run autoresearch) lives in OpenClaw's skills directory. The targets (what to optimize, their evals, and their results) live in `recess-brain` alongside the prompts they're improving. This keeps the optimization history co-located with the thing being optimized.

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

**Why not Cloud Run?** The loop needs to call Claude for both generation and scoring. OpenClaw already handles Claude API auth, sub-agent orchestration, and Slack reporting. Adding Cloud Run adds infra complexity for no gain at this stage. We can migrate to Cloud Run later if we need to run many targets in parallel.

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
                    │                  │ Output vs     │    │
                    │                  │ Eval Checklist│    │
                    │                  │ (binary Y/N)  │    │
                    │                  └──────┬───────┘    │
                    │                         │            │
                    │                    ▼         ▼       │
                    │              ┌────────┐ ┌────────┐   │
                    │              │ Score  │ │ Score  │   │
                    │              │ Better │ │ Worse  │   │
                    │              │→ KEEP  │ │→REVERT │   │
                    │              │→ Commit│ │→ Reset │   │
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
- **GitHub (gh CLI):** Committing improved prompts to recess-brain

The loop does NOT need all 8 MCPs active simultaneously, which avoids the ~70k context window collapse issue.

---

## 3. Eval Criteria Framework

### How Eval Criteria Work

Each target gets a **checklist of 3-6 binary (yes/no) questions**. A separate Claude call (Sonnet for cost efficiency) scores each output against the checklist. The score for a round = % of checks passed across all test inputs.

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

**Anti-gaming safeguard:** Every checklist MUST include one "holistic quality" criterion scored by a separate Claude call with the instruction: "Ignore the checklist. Read this as a human reader. Would you find this genuinely useful/interesting? Yes or No." This catches outputs that technically pass all criteria but read like garbage.

### Draft Eval Checklists

#### Target 1: LinkedIn Content Generation Prompt

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

#### Target 2: OpenClaw System Prompt

```markdown
## Eval Checklist: OpenClaw System Prompt

Test method: Give the system prompt to a fresh Claude instance with
5 diverse user messages. Score the RESPONSES.

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
```

#### Target 3: Campaign Recap Generation Prompt

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

### Phase 0: Foundation (Week 1)

**Goal:** Build the core loop and prove it works on a simple target.

**Deliverables:**

1. **SKILL.md** — OpenClaw skill definition for autoresearch
   - Trigger: "Run autoresearch on {target}"
   - References scripts, templates, target structure
   
2. **autoresearch-loop.py** — Core loop
   ```python
   # Pseudocode
   def run(target_dir, max_rounds=50, convergence_threshold=0.95, convergence_count=3):
       prompt = load(target_dir / "best-prompt.md")  # or original if first run
       eval_checklist = load(target_dir / "eval-checklist.md")
       test_inputs = load(target_dir / "test-inputs.json")
       program = load(target_dir / "program.md")
       
       baseline_score = score(prompt, test_inputs, eval_checklist)
       consecutive_converged = 0
       
       for round in range(max_rounds):
           # Mutate
           mutated_prompt = mutate(prompt, eval_checklist, last_failures, program)
           
           # Score
           new_score, failures = score(mutated_prompt, test_inputs, eval_checklist)
           
           # Keep or revert
           if new_score > baseline_score:
               prompt = mutated_prompt
               baseline_score = new_score
               log_round(round, "KEEP", new_score, diff)
               commit_to_git(prompt)
           else:
               log_round(round, "REVERT", new_score, diff)
           
           # Check convergence
           if new_score >= convergence_threshold:
               consecutive_converged += 1
               if consecutive_converged >= convergence_count:
                   break
           else:
               consecutive_converged = 0
       
       save_results(target_dir)
       post_summary_to_slack()
   ```

3. **scoring-engine.py** — Eval scorer
   - Takes: output text + eval checklist
   - Calls: Claude Sonnet 4 (cost efficient, good at structured eval)
   - Returns: per-criterion pass/fail + aggregate score
   - Structured output format to prevent scoring inconsistency

4. **mutation-engine.py** — Change proposer
   - Takes: current prompt + eval checklist + last round's failures
   - Calls: Claude Sonnet 4 with program.md context
   - Returns: exactly ONE small change + rationale
   - Constraint: mutations must be minimal (1-3 lines changed) to keep diffs reviewable

5. **results-logger.py** — Logging
   - Writes to `results.jsonl` (one JSON object per round)
   - Updates `changelog.md` with human-readable diffs
   - Updates `best-prompt.md` on improvements

6. **Revert mechanism**
   - Git-based: each improvement is a commit, reverts are `git checkout`
   - Backup: original prompt always preserved as `original-prompt.md` (never modified)

**Acceptance Criteria (Phase 0):**
- [ ] Can run `autoresearch-loop.py` against a test target from CLI
- [ ] Scoring engine returns consistent results on same input (>90% agreement on repeated runs)
- [ ] Mutation engine proposes small, relevant changes (not random rewrites)
- [ ] Results log captures every round with score, change, and keep/revert decision
- [ ] Git history shows clean commits for each kept improvement

### Phase 1: First Target (Week 2)

**Recommended first target: LinkedIn content generation prompt**

**Why this one first:**
- Highest iteration frequency (runs 3x/week via cron)
- Clear quality criteria (we already have voice-profile.json + banned phrases)
- Easy to generate diverse test inputs (different news stories, different content pillars)
- Results are immediately visible (better LinkedIn drafts = less editing for Deuce)
- Low risk — worst case, we keep the original prompt

**Steps:**
1. Define eval checklist with Deuce (draft above, refine together)
2. Create 10 diverse test inputs:
   - 3 CPG industry news stories
   - 3 sampling/retail media stories
   - 2 startup ops/leadership stories
   - 2 Fireflies transcript insights
3. Run baseline: score current prompt against checklist → establish starting point
4. Run 50 rounds overnight
5. Review results with Deuce:
   - Did the score actually improve?
   - Do the improved outputs read better to a human?
   - Any signs of checklist gaming?
6. If validated: deploy improved prompt to the LinkedIn generation pipeline
7. Document learnings in `recess-brain/decisions/autoresearch-v1-learnings.md`

**Acceptance Criteria (Phase 1):**
- [ ] Baseline score established and documented
- [ ] 50+ rounds completed without errors
- [ ] Final score measurably higher than baseline
- [ ] Deuce confirms improved outputs are actually better (human validation)
- [ ] Improved prompt deployed to production pipeline

### Phase 2: Dashboard + Automation (Weeks 3-4)

**Deliverables:**

1. **Slack command trigger**
   - `/autoresearch run linkedin-draft` → spawns sub-agent, posts results to thread
   - `/autoresearch status` → shows last run results per target
   - `/autoresearch history linkedin-draft` → shows score progression

2. **Results dashboard** (lightweight — don't overbuild)
   - **Option A: Slack-native** — Weekly summary posted to DM with score trends
   - **Option B: Google Sheet** — Auto-updated via Sheets MCP, shareable with team
   - **Option C: GitHub Pages** — Static HTML like our existing blockers dashboard
   - **Recommendation: Start with Option A** (Slack summary), add Option B if the team wants to explore data

3. **Scheduled runs**
   - OpenClaw cron: Run each target weekly (overnight, staggered)
   - Results posted to DM next morning
   - Auto-save improved prompts (original always preserved)

4. **Prompt version management**
   - `original-prompt.md` — Never modified (the starting point)
   - `best-prompt.md` — Current winner (updated by loop)
   - `best-prompt-v{N}.md` — Numbered snapshots for rollback
   - Production prompt always pulled from `best-prompt.md`

**Acceptance Criteria (Phase 2):**
- [ ] Can trigger autoresearch from Slack
- [ ] Results summary posted automatically after each run
- [ ] At least 2 targets running on weekly schedule
- [ ] Prompt versions tracked and rollback-capable

### Phase 3: Scale to All Key Prompts (Week 5+)

1. **Roll out to remaining targets:**
   - Campaign recap generation
   - OpenClaw system prompt
   - Meeting prep automation
   - Supply-side sales outreach
   - Landing page copy generator
   - BigQuery NL→SQL

2. **"Prompt Health" report**
   - Weekly aggregate: pass rates across all optimized prompts
   - Trend lines: are prompts improving, degrading, or stable?
   - Alert if any prompt drops below 80% (possible eval drift or input distribution change)

3. **Team adoption**
   - Template for team members to create their own autoresearch targets
   - Workshop in AI training curriculum: "How to write eval criteria"
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

---

## 5. Technical Specifications

### Model Selection

| Role | Model | Why |
|------|-------|-----|
| **Generation** (running the prompt being tested) | Same model used in production for that prompt | Results must reflect real-world performance |
| **Scoring** (evaluating outputs against checklist) | Claude Sonnet 4 | Cost efficient, excellent at structured evaluation, fast |
| **Mutation** (proposing changes) | Claude Sonnet 4 | Good at targeted edits, understands prompt engineering |
| **Anti-gaming check** | Claude Sonnet 4 (separate call, different system prompt) | Independent judgment |

### Cost Estimates

Per autoresearch run (50 rounds × 10 test inputs):

| Component | Calls | Avg tokens/call | Est. cost |
|-----------|-------|-----------------|-----------|
| Generation | 500 (50 rounds × 10 inputs) | ~1,500 out | ~$3.75 |
| Scoring | 500 (50 rounds × 10 inputs) | ~500 out | ~$1.25 |
| Anti-gaming | 500 | ~200 out | ~$0.50 |
| Mutation | 50 (1 per round) | ~1,000 out | ~$0.25 |
| **Total per run** | | | **~$5.75** |

At weekly runs across 5 targets: **~$29/week, ~$115/month**

This is extremely cheap compared to the human time it replaces (5-10 hours/week @ even $50/hr = $250-500/week).

### Configuration Defaults

```json
{
  "max_rounds": 50,
  "test_inputs_per_round": 10,
  "convergence_threshold": 0.95,
  "convergence_count": 3,
  "scoring_model": "claude-sonnet-4-20250514",
  "mutation_model": "claude-sonnet-4-20250514",
  "max_mutation_lines": 5,
  "budget_cap_usd": 10.00,
  "timeout_minutes": 120
}
```

### File Structure (Complete)

```
clawd/skills/autoresearch/
├── SKILL.md
├── scripts/
│   ├── autoresearch-loop.py
│   ├── scoring-engine.py
│   ├── mutation-engine.py
│   ├── results-logger.py
│   └── utils.py
├── templates/
│   ├── eval-checklist-template.md
│   ├── program-template.md
│   └── test-inputs-template.json
└── README.md

recess-brain/skills/autoresearch/
├── README.md                          # Overview + how to create targets
├── targets/
│   ├── linkedin-draft/
│   │   ├── program.md                 # Agent instructions for this target
│   │   ├── eval-checklist.md          # Binary eval criteria
│   │   ├── test-inputs.json           # Diverse test inputs
│   │   ├── original-prompt.md         # Never modified
│   │   └── .autoresearch/
│   │       ├── best-prompt.md         # Current best version
│   │       ├── results.jsonl          # Round-by-round log
│   │       └── changelog.md           # Human-readable history
│   ├── campaign-recap/
│   │   └── ...same structure...
│   ├── openclaw-system-prompt/
│   │   └── ...same structure...
│   └── ...more targets...
└── reports/
    └── prompt-health.md               # Weekly aggregate report
```

---

## 6. Risks & Constraints

### Context Window (HIGH risk)
- **Problem:** With 8 MCPs active, context can collapse to ~70k tokens
- **Mitigation:** Autoresearch runs as an isolated sub-agent with NO MCPs loaded. It only needs Claude API access (for generation/scoring) and filesystem access (for reading/writing prompts). MCPs are only needed for the trigger (Slack) and results reporting (Slack, BigQuery), which happen outside the loop.

### Cost Overrun (MEDIUM risk)
- **Problem:** Runaway loop or too many targets = unexpected API bill
- **Mitigation:** Hard budget cap per run ($10 default), max rounds (50), and timeout (2 hours). If budget is hit, loop stops and reports partial results.

### Prompt Drift (MEDIUM risk)
- **Problem:** Each mutation is small, but 50 small changes can collectively drift the prompt away from the original intent
- **Mitigation:** 
  1. Original prompt always preserved (never modified)
  2. The anti-gaming criterion catches coherence drift
  3. program.md includes explicit constraints ("maintain Deuce's voice," "keep under 200 words," etc.)
  4. Human review required before deploying any improved prompt to production (Phase 1 at minimum; can relax later)

### Checklist Gaming (MEDIUM risk)
- **Problem:** The mutation engine optimizes for passing the checklist, not for actual quality
- **Mitigation:**
  1. Anti-gaming criterion (separate Claude call, "would a human find this genuinely useful?")
  2. Diverse test inputs (the prompt must work across different scenarios, not just one)
  3. Periodic human review of improved prompts
  4. Checklist evolution — if gaming is detected, add criteria that catch the gaming pattern

### External System Dependencies (LOW risk for Phase 0-1)
- **Problem:** Some prompts need real data (BigQuery queries, HubSpot data) to test properly
- **Mitigation:** Phase 0-1 targets don't need external systems (LinkedIn drafts and system prompts work with synthetic inputs). For Phase 3 targets like BigQuery NL→SQL, we'll need to set up test datasets. This is a known future complexity, not a blocker.

### Scoring Consistency (MEDIUM risk)
- **Problem:** LLM-based scoring may not be deterministic — same output could score differently on two runs
- **Mitigation:**
  1. Use structured output (JSON) for scoring to reduce ambiguity
  2. Run scoring at temperature 0
  3. For close calls (within 5% of baseline), run scoring 3 times and take majority
  4. Validate scoring consistency in Phase 0 before trusting it for optimization

---

## 7. Success Metrics

### Primary Metrics

| Metric | Baseline | Phase 1 Target | Phase 3 Target |
|--------|----------|----------------|----------------|
| LinkedIn draft pass rate | TBD (measure in Phase 1) | 85%+ | 92%+ |
| Campaign recap pass rate | TBD | — | 90%+ |
| System prompt pass rate | TBD | — | 88%+ |
| Targets actively running | 0 | 1 | 5+ |
| Manual prompt editing time/week | ~5-10 hrs | ~3-5 hrs | ~1 hr |

### Secondary Metrics

- **Scoring consistency:** Same output scores within 5% on repeated runs
- **Mutation quality:** >30% of mutations are kept (vs. reverted) — lower means the mutation engine is guessing randomly
- **Convergence speed:** Reaches 90%+ within 30 rounds (vs. needing all 50)
- **Team adoption:** 2+ team members create their own targets by end of Phase 3
- **Cost efficiency:** <$6/run average

### How We Know It's NOT Working
- Pass rate improves but human reviewers say outputs are worse → checklist gaming, need to revise criteria
- Mutation keep rate <10% → mutation engine is too random, need better program.md
- Score plateaus early and never improves → eval criteria may be too easy or too hard
- Cost exceeds $15/run consistently → inefficiency in the loop, needs optimization

---

## 8. Open Questions for Deuce

### Decisions Needed

1. **First target confirmation:** I recommend LinkedIn draft generation. Agree, or prefer a different starting point?

2. **Eval criteria review:** The draft checklists above are starting points. Want to refine them together before Phase 0, or should I build the framework first and we iterate on criteria during Phase 1?

3. **Deployment approval flow:** When autoresearch finds a better prompt, should it:
   - (a) Auto-deploy to production immediately?
   - (b) Post the improved prompt for Deuce approval before deploying?
   - (c) Auto-deploy but keep original as instant rollback?
   - **Recommendation:** (b) for Phase 1, evolve to (c) once we trust the process

4. **Recess Brain access:** I don't currently have the `recess-brain` repo cloned locally. Need to clone it to set up the target directories. Is it at `github.com/deucethevenow/recess-brain` or a different org?

5. **Budget comfort:** Estimated ~$115/month at full scale (5 weekly targets). Is that within acceptable range, or should we cap lower?

6. **Team involvement:** Should we build this as a tool only Steve/Deuce use, or should it be accessible to the broader team from Phase 2 onward? (Affects how much we invest in UI/docs)

### Information Needed

1. **Campaign recap template:** I don't have the current campaign recap/case study generation prompt. Where does it live? (Make.com, a doc, a file somewhere?)

2. **Meeting prep prompt:** Where does the Lindy.ai meeting prep automation prompt live? Need to assess it as a Phase 3 target.

3. **Supply-side sales outreach prompt:** Same question — where does this live?

4. **Landing page copy generator:** Is this a Make.com automation or a standalone prompt? Where's the current version?

5. **BigQuery NL→SQL prompt:** I have the BigQuery skill in `clawd/skills/bigquery-query-agent/`. Is this the prompt we'd optimize, or is there a separate one in the CoS agent or elsewhere?

---

## Appendix A: Comparison to Karpathy's Original

| Aspect | Karpathy AutoResearch | Recess AutoResearch |
|--------|----------------------|---------------------|
| What's being optimized | PyTorch training code | Prompts & agent workflows |
| Metric | val_bpb (lower = better) | Eval checklist pass rate (higher = better) |
| What the agent modifies | `train.py` (one file) | Target prompt (one file) |
| Time per round | 5 min (GPU training) | ~30 sec (API calls) |
| Rounds per hour | ~12 | ~60-120 |
| Hardware required | NVIDIA GPU (H100) | None (API-based) |
| Scoring | Automatic (loss function) | LLM-judged (binary checklist) |
| Key risk | Overfitting to val set | Checklist gaming |

Our version is actually MORE efficient per round (seconds vs. minutes) but less precise in scoring (LLM judgment vs. mathematical loss). The anti-gaming safeguards are our answer to the precision gap.

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

---

*End of Task Packet. Ready for review.*
