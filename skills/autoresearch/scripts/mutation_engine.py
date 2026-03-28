#!/usr/bin/env python3
"""
Autoresearch Mutation Engine

Proposes one small change to a prompt based on eval failures.
Returns the mutated prompt text and a description of the change.

Temperature: 0.7 (creative variety to avoid repetitive proposals)
Model: Claude Sonnet 4
"""

import json
import os
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
    sys.exit(1)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
MUTATION_TEMPERATURE = 0.7
MAX_MUTATION_LINES = 5


def build_mutation_prompt(
    current_prompt: str,
    program: str,
    eval_checklist: str,
    last_round_results: dict | None = None,
    mutation_history: list[str] | None = None
) -> tuple[str, str]:
    """Build the system + user prompt for the mutation call."""
    
    system_prompt = """You are a prompt optimization specialist. Your job is to propose ONE small, 
targeted change to improve a prompt's performance against an eval checklist.

RULES:
1. Make exactly ONE change. Not two. Not three. ONE.
2. The change should be 1-5 lines maximum. Small, surgical edits.
3. Focus on the MOST COMMON failure from the last round.
4. Prefer general improvements (help across all inputs) over input-specific hacks.
5. Never reference specific test inputs in your mutation (that's overfitting).
6. If the same mutation was tried and reverted before, try a DIFFERENT approach.
7. Preserve the overall structure and intent of the prompt.

Respond with ONLY valid JSON:
{
  "change_description": "<one sentence describing what you changed and why>",
  "change_type": "<one of: add_instruction, modify_instruction, add_example, modify_example, add_constraint, remove_content, reword>",
  "lines_changed": <number of lines added/modified/removed>,
  "target_criterion": "<id of the criterion this change aims to improve>",
  "mutated_prompt": "<the COMPLETE prompt with your change applied>"
}

Output ONLY the JSON. No markdown fences, no explanation."""

    # Build context about failures
    failure_context = ""
    if last_round_results:
        per_criterion = last_round_results.get("per_criterion_pass_rates", {})
        if per_criterion:
            sorted_criteria = sorted(per_criterion.items(), key=lambda x: x[1])
            failure_context = "\n## Last Round Performance (per criterion)\n"
            for cid, rate in sorted_criteria:
                status = "🟢" if rate >= 0.8 else "🟡" if rate >= 0.5 else "🔴"
                failure_context += f"- {status} {cid}: {rate:.0%} pass rate\n"
            
            # Add specific failure reasoning if available
            worst_criterion = sorted_criteria[0][0] if sorted_criteria else None
            if worst_criterion and "individual_scores" in last_round_results:
                failure_context += f"\n### Failure examples for '{worst_criterion}':\n"
                count = 0
                for score_result in last_round_results["individual_scores"]:
                    for c in score_result.get("criteria", []):
                        if c["id"] == worst_criterion and not c["pass"] and count < 3:
                            failure_context += f"- {c['reasoning']}\n"
                            count += 1
    
    # Build mutation history context
    history_context = ""
    if mutation_history:
        recent = mutation_history[-10:]  # Last 10 mutations
        history_context = "\n## Recent Mutations (avoid repeating reverted ones)\n"
        for entry in recent:
            history_context += f"- {entry}\n"
    
    user_prompt = f"""## Program (constraints and strategy)

{program}

## Eval Checklist

{eval_checklist}

{failure_context}

{history_context}

## Current Prompt (make ONE small change to this)

{current_prompt}"""

    return system_prompt, user_prompt


def propose_mutation(
    client: anthropic.Anthropic,
    current_prompt: str,
    program: str,
    eval_checklist: str,
    last_round_results: dict | None = None,
    mutation_history: list[str] | None = None,
    model: str = DEFAULT_MODEL
) -> dict:
    """Propose one small mutation to the prompt.
    
    Returns:
        {
            "change_description": str,
            "change_type": str,
            "lines_changed": int,
            "target_criterion": str,
            "mutated_prompt": str
        }
    """
    system_prompt, user_prompt = build_mutation_prompt(
        current_prompt, program, eval_checklist, last_round_results, mutation_history
    )
    
    response = client.messages.create(
        model=model,
        max_tokens=8000,  # Needs room for full prompt in output
        temperature=MUTATION_TEMPERATURE,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    raw_text = response.content[0].text.strip()
    
    # Strip markdown fences if present
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text.rsplit("```", 1)[0]
        raw_text = raw_text.strip()
    
    result = json.loads(raw_text)
    
    # Validate
    assert "mutated_prompt" in result, "Missing 'mutated_prompt' in response"
    assert "change_description" in result, "Missing 'change_description' in response"
    
    # Enforce max mutation lines
    if result.get("lines_changed", 0) > MAX_MUTATION_LINES:
        # Still allow it but flag it
        result["warning"] = f"Mutation claims {result['lines_changed']} lines changed (max recommended: {MAX_MUTATION_LINES})"
    
    return result


def compute_diff(original: str, mutated: str) -> str:
    """Compute a simple line-level diff between original and mutated prompts."""
    import difflib
    
    original_lines = original.splitlines(keepends=True)
    mutated_lines = mutated.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        original_lines, mutated_lines,
        fromfile="before", tofile="after",
        lineterm=""
    )
    
    return "".join(diff)


# --- CLI ---

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Propose a mutation to a prompt")
    parser.add_argument("--prompt", required=True, help="Path to current prompt")
    parser.add_argument("--program", required=True, help="Path to program.md")
    parser.add_argument("--checklist", required=True, help="Path to eval checklist")
    parser.add_argument("--last-results", help="Path to last round results JSON")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    
    args = parser.parse_args()
    
    client = anthropic.Anthropic()
    
    current_prompt = Path(args.prompt).read_text()
    program = Path(args.program).read_text()
    eval_checklist = Path(args.checklist).read_text()
    
    last_results = None
    if args.last_results:
        last_results = json.loads(Path(args.last_results).read_text())
    
    result = propose_mutation(
        client, current_prompt, program, eval_checklist,
        last_round_results=last_results, model=args.model
    )
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"\n=== Proposed Mutation ===")
        print(f"Target: {result.get('target_criterion', 'unknown')}")
        print(f"Type: {result.get('change_type', 'unknown')}")
        print(f"Lines changed: {result.get('lines_changed', '?')}")
        print(f"Description: {result['change_description']}")
        if "warning" in result:
            print(f"⚠️  {result['warning']}")
        print(f"\n--- Diff ---")
        print(compute_diff(current_prompt, result["mutated_prompt"]))
