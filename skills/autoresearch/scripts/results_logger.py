#!/usr/bin/env python3
"""
Autoresearch Results Logger

Handles round-by-round logging to JSONL, changelog updates, and best-prompt management.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class ResultsLogger:
    """Manages autoresearch results for a target."""
    
    def __init__(self, target_dir: str):
        self.target_dir = Path(target_dir)
        self.ar_dir = self.target_dir / ".autoresearch"
        self.ar_dir.mkdir(parents=True, exist_ok=True)
        
        self.results_file = self.ar_dir / "results.jsonl"
        self.changelog_file = self.ar_dir / "changelog.md"
        self.best_prompt_file = self.ar_dir / "best-prompt.md"
    
    def log_round(
        self,
        round_num: int,
        action: str,  # "KEEP", "REVERT", "REVERT (anti-gaming)"
        score: float,
        baseline_score: float,
        change_description: str = "",
        change_type: str = "",
        target_criterion: str = "",
        diff: str = "",
        per_criterion_pass_rates: dict = None,
        anti_gaming_failures: int = 0,
        cost_usd: float = 0.0
    ):
        """Log a single round result to JSONL."""
        entry = {
            "round": round_num,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "score": score,
            "baseline_score": baseline_score,
            "change_description": change_description,
            "change_type": change_type,
            "target_criterion": target_criterion,
            "per_criterion_pass_rates": per_criterion_pass_rates or {},
            "anti_gaming_failures": anti_gaming_failures,
            "cost_usd": round(cost_usd, 4)
        }
        
        with open(self.results_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        # Update changelog for KEEP actions
        if action == "KEEP":
            self._append_changelog(round_num, score, change_description, change_type, target_criterion)
    
    def _append_changelog(
        self,
        round_num: int,
        score: float,
        change_description: str,
        change_type: str,
        target_criterion: str
    ):
        """Append a kept change to the human-readable changelog."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        entry = f"\n## Round {round_num} — Score: {score:.1%} ({timestamp})\n"
        entry += f"- **Type:** {change_type}\n"
        entry += f"- **Target criterion:** {target_criterion}\n"
        entry += f"- **Change:** {change_description}\n"
        
        if not self.changelog_file.exists():
            header = f"# Autoresearch Changelog: {self.target_dir.name}\n\n"
            header += "Each entry represents a mutation that improved the score and was kept.\n"
            self.changelog_file.write_text(header)
        
        with open(self.changelog_file, "a") as f:
            f.write(entry)
    
    def save_best_prompt(self, prompt_text: str, round_num: int, score: float):
        """Save the current best prompt version."""
        header = f"<!-- Autoresearch best prompt | Round {round_num} | Score: {score:.1%} | {datetime.now().isoformat()} -->\n\n"
        self.best_prompt_file.write_text(header + prompt_text)
    
    def save_versioned_prompt(self, prompt_text: str, version: int, score: float):
        """Save a numbered version snapshot for rollback."""
        version_file = self.ar_dir / f"best-prompt-v{version}.md"
        header = f"<!-- Version {version} | Score: {score:.1%} | {datetime.now().isoformat()} -->\n\n"
        version_file.write_text(header + prompt_text)
    
    def get_run_summary(self) -> dict:
        """Generate a summary of the current/last run from the results log."""
        if not self.results_file.exists():
            return {"status": "no_results", "rounds": 0}
        
        rounds = []
        with open(self.results_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    rounds.append(json.loads(line))
        
        if not rounds:
            return {"status": "no_results", "rounds": 0}
        
        keeps = [r for r in rounds if r["action"] == "KEEP"]
        reverts = [r for r in rounds if r["action"].startswith("REVERT")]
        
        first_score = rounds[0]["baseline_score"]
        final_score = rounds[-1]["score"] if rounds[-1]["action"] == "KEEP" else rounds[-1]["baseline_score"]
        
        total_cost = sum(r.get("cost_usd", 0) for r in rounds)
        
        return {
            "status": "complete",
            "total_rounds": len(rounds),
            "keeps": len(keeps),
            "reverts": len(reverts),
            "keep_rate": len(keeps) / len(rounds) if rounds else 0,
            "starting_score": first_score,
            "final_score": final_score,
            "improvement": final_score - first_score,
            "total_cost_usd": round(total_cost, 2),
            "best_round": max(rounds, key=lambda r: r["score"])["round"] if rounds else None
        }
    
    def format_summary_for_slack(self) -> str:
        """Format the run summary as a Slack-friendly message."""
        summary = self.get_run_summary()
        
        if summary["status"] == "no_results":
            return "No autoresearch results found for this target."
        
        improvement_emoji = "📈" if summary["improvement"] > 0 else "📉" if summary["improvement"] < 0 else "➡️"
        
        msg = f"AUTORESEARCH COMPLETE: {self.target_dir.name}\n\n"
        msg += f"{improvement_emoji} Score: {summary['starting_score']:.1%} → {summary['final_score']:.1%} "
        msg += f"({summary['improvement']:+.1%})\n"
        msg += f"Rounds: {summary['total_rounds']} ({summary['keeps']} kept, {summary['reverts']} reverted)\n"
        msg += f"Keep rate: {summary['keep_rate']:.0%}\n"
        msg += f"Cost: ${summary['total_cost_usd']:.2f}\n"
        
        if summary['keeps'] == 0:
            msg += "\nNo improvements found. The current prompt may already be well-optimized, or the eval criteria may need adjustment."
        
        return msg


# --- CLI ---

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="View autoresearch results")
    parser.add_argument("target_dir", help="Path to target directory")
    parser.add_argument("--summary", action="store_true", help="Show run summary")
    parser.add_argument("--slack", action="store_true", help="Format for Slack")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    
    args = parser.parse_args()
    
    logger = ResultsLogger(args.target_dir)
    
    if args.slack:
        print(logger.format_summary_for_slack())
    elif args.summary or args.json:
        summary = logger.get_run_summary()
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"\n=== Run Summary: {Path(args.target_dir).name} ===")
            if summary["status"] == "no_results":
                print("No results found.")
            else:
                print(f"Rounds: {summary['total_rounds']} ({summary['keeps']} kept, {summary['reverts']} reverted)")
                print(f"Score: {summary['starting_score']:.1%} → {summary['final_score']:.1%} ({summary['improvement']:+.1%})")
                print(f"Keep rate: {summary['keep_rate']:.0%}")
                print(f"Cost: ${summary['total_cost_usd']:.2f}")
