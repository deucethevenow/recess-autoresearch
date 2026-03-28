#!/usr/bin/env python3
"""
Autoresearch Scoring Engine

Evaluates prompt outputs against a binary eval checklist using Claude Sonnet.
Returns structured JSON with per-criterion pass/fail, reasoning, anti-gaming check, and aggregate score.

Temperature: 0 (deterministic scoring)
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
SCORING_TEMPERATURE = 0

# --- Schema ---

SCORING_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question": {"type": "string"},
                    "pass": {"type": "boolean"},
                    "reasoning": {"type": "string"}
                },
                "required": ["id", "question", "pass", "reasoning"]
            }
        },
        "total_pass": {"type": "integer"},
        "total_criteria": {"type": "integer"},
        "score": {"type": "number"},
        "anti_gaming_pass": {"type": "boolean"},
        "anti_gaming_reasoning": {"type": "string"}
    },
    "required": ["criteria", "total_pass", "total_criteria", "score", "anti_gaming_pass", "anti_gaming_reasoning"]
}


def load_eval_checklist(checklist_path: str) -> list[dict]:
    """Parse an eval checklist markdown file into structured criteria.
    
    Expected format per criterion:
    N. ID: Question text
       → Yes/No
    """
    text = Path(checklist_path).read_text()
    criteria = []
    lines = text.strip().split("\n")
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Match lines like "1. HOOK: Does the first line..."
        if line and line[0].isdigit() and "." in line.split()[0]:
            # Extract ID and question
            after_num = line.split(".", 1)[1].strip()
            if ":" in after_num:
                cid, question = after_num.split(":", 1)
                cid = cid.strip().lower()
                question = question.strip()
                # Collect continuation lines until we hit → or next numbered item
                i += 1
                while i < len(lines):
                    next_line = lines[i].strip()
                    if next_line.startswith("→") or next_line.startswith("->"):
                        break
                    if next_line and next_line[0].isdigit() and "." in next_line.split()[0]:
                        break
                    if next_line:
                        question += " " + next_line
                    i += 1
                criteria.append({"id": cid, "question": question})
                continue
        i += 1
    
    return criteria


def build_scoring_prompt(output_text: str, criteria: list[dict]) -> str:
    """Build the system + user prompt for the scoring call."""
    
    criteria_text = "\n".join(
        f'{i+1}. **{c["id"]}**: {c["question"]}'
        for i, c in enumerate(criteria)
    )
    
    system_prompt = """You are an evaluator scoring text output against a binary checklist.

For each criterion, determine if the output PASSES (true) or FAILS (false).
Provide specific reasoning citing exact text from the output.

Additionally, provide an anti-gaming assessment: Ignore the checklist entirely. 
Read the output as a real human reader. Would you find this genuinely useful, 
interesting, or well-crafted? This catches outputs that technically pass criteria 
but are actually garbage.

Respond with ONLY valid JSON matching this exact schema:
{
  "criteria": [
    {
      "id": "<criterion_id>",
      "question": "<the criterion question>",
      "pass": true/false,
      "reasoning": "<one sentence citing specific text>"
    }
  ],
  "total_pass": <number of criteria that passed>,
  "total_criteria": <total number of criteria>,
  "score": <total_pass / total_criteria as decimal>,
  "anti_gaming_pass": true/false,
  "anti_gaming_reasoning": "<honest assessment of holistic quality>"
}

RULES:
- Be strict. "Close enough" is a FAIL.
- Reasoning must cite specific text from the output, not just say "it does/doesn't".
- The anti-gaming check is INDEPENDENT of the criteria. A post can pass all criteria but fail anti-gaming (or vice versa).
- Score must equal total_pass / total_criteria exactly.
- Output ONLY the JSON object. No markdown fences, no explanation."""
    
    user_prompt = f"""## Eval Criteria

{criteria_text}

## Output to Evaluate

{output_text}"""
    
    return system_prompt, user_prompt


def score_single_output(
    client: anthropic.Anthropic,
    output_text: str,
    criteria: list[dict],
    model: str = DEFAULT_MODEL
) -> dict:
    """Score a single output against the eval checklist.
    
    Returns the structured scoring response dict.
    """
    system_prompt, user_prompt = build_scoring_prompt(output_text, criteria)
    
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        temperature=SCORING_TEMPERATURE,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    raw_text = response.content[0].text.strip()
    
    # Strip markdown fences if model wraps in ```json
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text.rsplit("```", 1)[0]
        raw_text = raw_text.strip()
    
    result = json.loads(raw_text)
    
    # Validate structure
    assert "criteria" in result, "Missing 'criteria' in response"
    assert "score" in result, "Missing 'score' in response"
    assert "anti_gaming_pass" in result, "Missing 'anti_gaming_pass' in response"
    
    # Verify score calculation
    expected_score = result["total_pass"] / result["total_criteria"] if result["total_criteria"] > 0 else 0
    if abs(result["score"] - expected_score) > 0.01:
        result["score"] = round(expected_score, 3)
    
    return result


def score_round(
    client: anthropic.Anthropic,
    outputs: list[str],
    criteria: list[dict],
    model: str = DEFAULT_MODEL
) -> dict:
    """Score all outputs for a single round.
    
    Returns:
        {
            "round_score": float,  # average score across all outputs
            "individual_scores": [dict],  # per-output scoring results
            "anti_gaming_failures": int,  # count of outputs failing anti-gaming
            "per_criterion_pass_rates": {criterion_id: float},  # pass rate per criterion
        }
    """
    individual_scores = []
    anti_gaming_failures = 0
    criterion_passes = {}
    criterion_totals = {}
    
    for output_text in outputs:
        result = score_single_output(client, output_text, criteria, model)
        individual_scores.append(result)
        
        if not result.get("anti_gaming_pass", True):
            anti_gaming_failures += 1
        
        for c in result.get("criteria", []):
            cid = c["id"]
            criterion_passes[cid] = criterion_passes.get(cid, 0) + (1 if c["pass"] else 0)
            criterion_totals[cid] = criterion_totals.get(cid, 0) + 1
    
    # Average score across all outputs
    round_score = sum(r["score"] for r in individual_scores) / len(individual_scores) if individual_scores else 0
    
    # Per-criterion pass rates
    per_criterion = {
        cid: criterion_passes[cid] / criterion_totals[cid]
        for cid in criterion_passes
    }
    
    return {
        "round_score": round(round_score, 3),
        "individual_scores": individual_scores,
        "anti_gaming_failures": anti_gaming_failures,
        "per_criterion_pass_rates": per_criterion
    }


def check_scoring_consistency(
    client: anthropic.Anthropic,
    output_text: str,
    criteria: list[dict],
    runs: int = 3,
    model: str = DEFAULT_MODEL
) -> dict:
    """Run scoring multiple times on the same output to check consistency.
    
    Returns agreement rate and individual results.
    """
    results = []
    for _ in range(runs):
        result = score_single_output(client, output_text, criteria, model)
        results.append(result)
    
    # Check agreement per criterion
    agreements = {}
    for cid_idx, c in enumerate(results[0]["criteria"]):
        cid = c["id"]
        votes = [r["criteria"][cid_idx]["pass"] for r in results]
        agreement = max(votes.count(True), votes.count(False)) / len(votes)
        agreements[cid] = agreement
    
    overall_agreement = sum(agreements.values()) / len(agreements) if agreements else 0
    
    return {
        "overall_agreement": round(overall_agreement, 3),
        "per_criterion_agreement": agreements,
        "scores": [r["score"] for r in results],
        "individual_results": results
    }


# --- CLI ---

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Score output against eval checklist")
    parser.add_argument("--checklist", required=True, help="Path to eval checklist markdown")
    parser.add_argument("--output", required=True, help="Path to output text file to score")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use for scoring")
    parser.add_argument("--consistency-check", action="store_true", help="Run 3x and check agreement")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    
    args = parser.parse_args()
    
    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
    criteria = load_eval_checklist(args.checklist)
    output_text = Path(args.output).read_text()
    
    if args.consistency_check:
        result = check_scoring_consistency(client, output_text, criteria, model=args.model)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\n=== Scoring Consistency Check ({3} runs) ===")
            print(f"Overall agreement: {result['overall_agreement']:.1%}")
            print(f"Scores: {result['scores']}")
            for cid, agr in result["per_criterion_agreement"].items():
                print(f"  {cid}: {agr:.0%} agreement")
    else:
        result = score_single_output(client, output_text, criteria, model=args.model)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\n=== Scoring Result ===")
            print(f"Score: {result['score']:.1%} ({result['total_pass']}/{result['total_criteria']})")
            print(f"Anti-gaming: {'PASS' if result['anti_gaming_pass'] else 'FAIL'}")
            print(f"  → {result['anti_gaming_reasoning']}")
            print()
            for c in result["criteria"]:
                status = "✅" if c["pass"] else "❌"
                print(f"  {status} {c['id']}: {c['reasoning']}")
