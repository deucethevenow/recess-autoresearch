---
name: autoresearch
description: Autonomously optimize prompts and agent workflows by running an eval-mutate-score loop. Inspired by Karpathy's AutoResearch. Use when asked to optimize, improve, or autoresearch any prompt target.
---

# Autoresearch Skill

Run autonomous prompt optimization loops against defined targets.

## Quick Start

```bash
# Dry run (baseline scoring only)
cd ~/clawd/skills/autoresearch
python3 scripts/autoresearch_loop.py --target targets/linkedin-draft/ --dry-run

# Full run (50 rounds)
python3 scripts/autoresearch_loop.py --target targets/linkedin-draft/

# Limited run
python3 scripts/autoresearch_loop.py --target targets/linkedin-draft/ --max-rounds 10
```

## Requires
- `ANTHROPIC_API_KEY` environment variable
- `pip install anthropic` (Python anthropic SDK)

## Target Structure

Each target directory must contain:
- `program.md` — Instructions for the mutation engine
- `eval-checklist.md` — Binary yes/no eval criteria (3-6 items)
- `test-inputs.json` — Array of test input objects with `user_message` and optional `context`
- `original-prompt.md` — The starting prompt (never modified by the loop)

Results are written to `.autoresearch/` subdirectory:
- `best-prompt.md` — Current winning prompt version
- `results.jsonl` — Round-by-round log
- `changelog.md` — Human-readable mutation history

## Available Targets
- `targets/linkedin-draft/` — LinkedIn content generation prompt (Phase 0)
- `targets/openclaw-system-prompt/` — OpenClaw system prompt (Phase 1)

## Standalone Tools

```bash
# Score a single output
python3 scripts/scoring_engine.py --checklist targets/linkedin-draft/eval-checklist.md --output /path/to/output.txt

# Check scoring consistency (3 runs)
python3 scripts/scoring_engine.py --checklist targets/linkedin-draft/eval-checklist.md --output /path/to/output.txt --consistency-check

# Propose a mutation
python3 scripts/mutation_engine.py --prompt targets/linkedin-draft/original-prompt.md --program targets/linkedin-draft/program.md --checklist targets/linkedin-draft/eval-checklist.md

# View results
python3 scripts/results_logger.py targets/linkedin-draft/ --summary
python3 scripts/results_logger.py targets/linkedin-draft/ --slack
```

## Key Config (override via targets/{name}/config.json)
- `max_rounds`: 50
- `convergence_threshold`: 0.95 (3 of last 5 rounds)
- `scoring_temperature`: 0
- `mutation_temperature`: 0.7
- `budget_cap_usd`: 10.00
- `anti_gaming_block_threshold`: 3 (of 10 inputs)
