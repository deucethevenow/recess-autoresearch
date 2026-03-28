#!/usr/bin/env python3
"""
Autoresearch Loop Runner

The core autonomous prompt optimization loop. Runs N rounds of:
  mutate → generate → score → keep/revert

Usage:
    python autoresearch_loop.py --target targets/linkedin-draft/ [--max-rounds 50] [--dry-run]
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
    sys.exit(1)

# Add scripts dir to path for imports
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from scoring_engine import load_eval_checklist, score_round
from mutation_engine import propose_mutation, compute_diff
from results_logger import ResultsLogger

# --- Configuration ---

DEFAULT_CONFIG = {
    "max_rounds": 50,
    "test_inputs_per_round": 10,
    "convergence_threshold": 0.95,
    "convergence_window": 5,
    "convergence_required": 3,
    "scoring_model": "claude-sonnet-4-20250514",
    "scoring_temperature": 0,
    "mutation_model": "claude-sonnet-4-20250514",
    "mutation_temperature": 0.7,
    "generation_model": "claude-sonnet-4-20250514",
    "generation_temperature": 1.0,
    "max_mutation_lines": 5,
    "anti_gaming_block_threshold": 3,
    "anti_gaming_audit_interval": 10,
    "budget_cap_usd": 10.00,
    "timeout_minutes": 120
}


def load_config(target_dir: Path) -> dict:
    """Load config, merging target-specific overrides with defaults."""
    config = DEFAULT_CONFIG.copy()
    config_file = target_dir / "config.json"
    if config_file.exists():
        overrides = json.loads(config_file.read_text())
        config.update(overrides)
    return config


def load_test_inputs(target_dir: Path) -> list[dict]:
    """Load test inputs from JSON file."""
    inputs_file = target_dir / "test-inputs.json"
    if not inputs_file.exists():
        raise FileNotFoundError(f"No test-inputs.json found in {target_dir}")
    return json.loads(inputs_file.read_text())


def generate_output(
    client: anthropic.Anthropic,
    prompt: str,
    test_input: dict,
    model: str,
    temperature: float
) -> str:
    """Run the target prompt against a single test input to produce an output."""
    # The test input may have a "user_message" field (what the user says)
    # and optional context fields
    user_message = test_input.get("user_message", test_input.get("input", ""))
    context = test_input.get("context", "")
    
    # Build the full user message with context if provided
    full_user = ""
    if context:
        full_user += f"{context}\n\n"
    full_user += user_message
    
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        temperature=temperature,
        system=prompt,
        messages=[{"role": "user", "content": full_user}]
    )
    
    return response.content[0].text


def run_autoresearch(
    target_dir: str,
    max_rounds: int | None = None,
    dry_run: bool = False,
    verbose: bool = False
) -> dict:
    """Run the full autoresearch loop on a target.
    
    Returns the run summary dict.
    """
    target_path = Path(target_dir)
    config = load_config(target_path)
    
    if max_rounds is not None:
        config["max_rounds"] = max_rounds
    
    # Load target files
    program = (target_path / "program.md").read_text()
    eval_checklist_text = (target_path / "eval-checklist.md").read_text()
    criteria = load_eval_checklist(str(target_path / "eval-checklist.md"))
    test_inputs = load_test_inputs(target_path)
    
    # Load current best prompt (or original if first run)
    best_prompt_path = target_path / ".autoresearch" / "best-prompt.md"
    original_prompt_path = target_path / "original-prompt.md"
    
    if best_prompt_path.exists():
        # Strip the metadata comment header if present
        text = best_prompt_path.read_text()
        if text.startswith("<!--"):
            text = text.split("-->\n", 1)[-1].strip()
        current_prompt = text
    elif original_prompt_path.exists():
        current_prompt = original_prompt_path.read_text()
    else:
        raise FileNotFoundError(f"No prompt found. Need either {best_prompt_path} or {original_prompt_path}")
    
    # Initialize
    client = anthropic.Anthropic()
    logger = ResultsLogger(target_dir)
    mutation_history = []
    total_cost = 0.0
    start_time = time.time()
    version_counter = 0
    
    print(f"\n{'='*60}")
    print(f"AUTORESEARCH: {target_path.name}")
    print(f"{'='*60}")
    print(f"Config: {config['max_rounds']} max rounds, {len(test_inputs)} test inputs")
    print(f"Convergence: {config['convergence_threshold']:.0%} on {config['convergence_required']}/{config['convergence_window']} rounds")
    print(f"Budget cap: ${config['budget_cap_usd']:.2f}")
    print(f"{'='*60}\n")
    
    # --- Baseline scoring ---
    print("Running baseline scoring...")
    baseline_outputs = []
    for ti in test_inputs:
        output = generate_output(
            client, current_prompt, ti,
            config["generation_model"], config["generation_temperature"]
        )
        baseline_outputs.append(output)
    
    baseline_result = score_round(client, baseline_outputs, criteria, config["scoring_model"])
    baseline_score = baseline_result["round_score"]
    
    print(f"Baseline score: {baseline_score:.1%}")
    print(f"Per-criterion: {json.dumps(baseline_result['per_criterion_pass_rates'], indent=2)}")
    print(f"Anti-gaming failures: {baseline_result['anti_gaming_failures']}/{len(test_inputs)}")
    print()
    
    if dry_run:
        print("DRY RUN — stopping after baseline.")
        return {"baseline_score": baseline_score, "per_criterion": baseline_result["per_criterion_pass_rates"]}
    
    # --- Main loop ---
    recent_scores = []
    
    for round_num in range(1, config["max_rounds"] + 1):
        elapsed = (time.time() - start_time) / 60
        
        # Budget check
        if total_cost >= config["budget_cap_usd"]:
            print(f"\n⚠️  Budget cap reached (${total_cost:.2f} >= ${config['budget_cap_usd']:.2f}). Stopping.")
            break
        
        # Timeout check
        if elapsed >= config["timeout_minutes"]:
            print(f"\n⚠️  Timeout reached ({elapsed:.0f}min >= {config['timeout_minutes']}min). Stopping.")
            break
        
        print(f"--- Round {round_num}/{config['max_rounds']} (score: {baseline_score:.1%}, cost: ${total_cost:.2f}) ---")
        
        # 1. Mutate
        try:
            mutation = propose_mutation(
                client, current_prompt, program, eval_checklist_text,
                last_round_results=baseline_result,
                mutation_history=mutation_history,
                model=config["mutation_model"]
            )
        except Exception as e:
            print(f"  ⚠️  Mutation failed: {e}. Skipping round.")
            continue
        
        mutated_prompt = mutation["mutated_prompt"]
        change_desc = mutation["change_description"]
        print(f"  Mutation: {change_desc}")
        
        # 2. Generate outputs with mutated prompt
        outputs = []
        for ti in test_inputs:
            try:
                output = generate_output(
                    client, mutated_prompt, ti,
                    config["generation_model"], config["generation_temperature"]
                )
                outputs.append(output)
            except Exception as e:
                print(f"  ⚠️  Generation failed for input: {e}")
                outputs.append("")
        
        # 3. Score
        try:
            round_result = score_round(client, outputs, criteria, config["scoring_model"])
        except Exception as e:
            print(f"  ⚠️  Scoring failed: {e}. Skipping round.")
            continue
        
        new_score = round_result["round_score"]
        anti_gaming_failures = round_result["anti_gaming_failures"]
        
        # Estimate cost for this round (rough)
        round_cost = len(test_inputs) * 0.01 + 0.005  # ~$0.01/input for gen+score, $0.005 for mutation
        total_cost += round_cost
        
        # 4. Anti-gaming gate
        if anti_gaming_failures >= config["anti_gaming_block_threshold"]:
            action = "REVERT (anti-gaming)"
            print(f"  ❌ REVERT (anti-gaming): {anti_gaming_failures}/{len(test_inputs)} failed holistic check")
            mutation_history.append(f"[REVERT-ANTIGAMING] {change_desc}")
            logger.log_round(
                round_num, action, new_score, baseline_score,
                change_desc, mutation.get("change_type", ""),
                mutation.get("target_criterion", ""),
                per_criterion_pass_rates=round_result["per_criterion_pass_rates"],
                anti_gaming_failures=anti_gaming_failures,
                cost_usd=round_cost
            )
            recent_scores.append(baseline_score)  # Score didn't change
            continue
        
        # 5. Keep or revert — equal scores are reverted (mutations must earn their place)
        if new_score > baseline_score:
            action = "KEEP"
            print(f"  ✅ KEEP: {baseline_score:.1%} → {new_score:.1%} (+{new_score - baseline_score:.1%})")
            
            current_prompt = mutated_prompt
            baseline_score = new_score
            baseline_result = round_result
            
            version_counter += 1
            logger.save_best_prompt(current_prompt, round_num, new_score)
            logger.save_versioned_prompt(current_prompt, version_counter, new_score)
            mutation_history.append(f"[KEEP] {change_desc}")
        else:
            action = "REVERT"
            reason = "equal score — mutations must earn their place" if new_score == baseline_score else f"worse ({new_score:.1%} < {baseline_score:.1%})"
            print(f"  ↩️  REVERT: {reason}")
            mutation_history.append(f"[REVERT] {change_desc}")
        
        logger.log_round(
            round_num, action, new_score, baseline_score,
            change_desc, mutation.get("change_type", ""),
            mutation.get("target_criterion", ""),
            per_criterion_pass_rates=round_result["per_criterion_pass_rates"],
            anti_gaming_failures=anti_gaming_failures,
            cost_usd=round_cost
        )
        
        # 6. Full anti-gaming audit every N rounds
        if round_num % config["anti_gaming_audit_interval"] == 0:
            print(f"  🔍 Anti-gaming audit (round {round_num})...")
            # Re-score current best with fresh eyes
            audit_outputs = []
            for ti in test_inputs:
                output = generate_output(
                    client, current_prompt, ti,
                    config["generation_model"], config["generation_temperature"]
                )
                audit_outputs.append(output)
            audit_result = score_round(client, audit_outputs, criteria, config["scoring_model"])
            audit_ag_failures = audit_result["anti_gaming_failures"]
            print(f"  🔍 Audit result: {audit_result['round_score']:.1%}, anti-gaming failures: {audit_ag_failures}/{len(test_inputs)}")
        
        # 7. Convergence check: 95%+ on 3 of last 5 rounds
        recent_scores.append(new_score if action == "KEEP" else baseline_score)
        if len(recent_scores) > config["convergence_window"]:
            recent_scores.pop(0)
        
        if len(recent_scores) >= config["convergence_window"]:
            converged_count = sum(
                1 for s in recent_scores
                if s >= config["convergence_threshold"]
            )
            if converged_count >= config["convergence_required"]:
                print(f"\n🎯 Converged! {converged_count}/{config['convergence_window']} recent rounds at {config['convergence_threshold']:.0%}+")
                break
    
    # --- Final summary ---
    elapsed_total = (time.time() - start_time) / 60
    summary = logger.get_run_summary()
    
    print(f"\n{'='*60}")
    print(f"COMPLETE: {target_path.name}")
    print(f"{'='*60}")
    print(f"Time: {elapsed_total:.1f} minutes")
    print(f"Rounds: {summary.get('total_rounds', 0)}")
    print(f"Score: {summary.get('starting_score', 0):.1%} → {summary.get('final_score', 0):.1%}")
    print(f"Improvements: {summary.get('keeps', 0)} kept, {summary.get('reverts', 0)} reverted")
    print(f"Keep rate: {summary.get('keep_rate', 0):.0%}")
    print(f"Cost: ~${total_cost:.2f}")
    print(f"{'='*60}\n")
    
    return summary


# --- CLI ---

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run autoresearch loop on a target")
    parser.add_argument("--target", required=True, help="Path to target directory")
    parser.add_argument("--max-rounds", type=int, help="Override max rounds")
    parser.add_argument("--dry-run", action="store_true", help="Only run baseline scoring, no mutations")
    parser.add_argument("--verbose", action="store_true", help="Extra logging")
    
    args = parser.parse_args()
    
    summary = run_autoresearch(
        args.target,
        max_rounds=args.max_rounds,
        dry_run=args.dry_run,
        verbose=args.verbose
    )
    
    print(json.dumps(summary, indent=2))
