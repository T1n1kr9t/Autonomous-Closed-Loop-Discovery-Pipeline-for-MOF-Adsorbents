"""Main Entry Point for Senior Project Closed-Loop Pipeline.

Usage:
    python src/pipeline.py --target 3
"""

import sys
import argparse
import logging
from pathlib import Path
from tabulate import tabulate

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Auto-load .env
try:
    from dotenv import load_dotenv
    load_dotenv(root_dir / ".env")
except ImportError:
    pass

from src.agents.orchestrator import PipelineOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("PipelineMain")


def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Closed-Loop MOF Discovery Pipeline")
    parser.add_argument("--target", type=int, default=3, help="Number of successful candidates to discover")
    parser.add_argument("--max-trials", type=int, default=10, help="Maximum search cycles allowed")
    parser.add_argument("--no-wsl", action="store_true", help="Disable WSL integration (run purely native or mock)")
    args = parser.parse_args()

    print("=" * 70)
    print("  Senior Project: Closed-Loop AI Pipeline for MOF GHG Adsorbents")
    print("=" * 70)

    orchestrator = PipelineOrchestrator(use_wsl=not args.no_wsl)
    candidates = orchestrator.run_discovery_campaign(
        target_successes=args.target,
        max_iterations=args.max_trials
    )

    print("\n" + "=" * 70)
    print("  DISCOVERY CAMPAIGN SUMMARY")
    print("=" * 70)

    if not candidates:
        print("No candidates successfully passed all screening and simulation stages.")
        return

    table_data = []
    for c in candidates:
        table_data.append([
            c["candidate_name"],
            c["smiles"][:30] + ("..." if len(c["smiles"]) > 30 else ""),
            f"{c['pld_angstrom']:.2f} Å",
            f"{c['co2_loading_mol_kg']:.2f}",
            f"{c['ch4_loading_mol_kg']:.2f}",
            f"{c['selectivity_co2_ch4']:.2f}"
        ])

    headers = ["Candidate", "Linker SMILES", "PLD (Å)", "CO2 Load (mol/kg)", "CH4 Load (mol/kg)", "Selectivity S(CO2/CH4)"]
    print(tabulate(table_data, headers=headers, tablefmt="github"))
    print("\nResults successfully saved to: data/database/success_candidates.json")
    print("Active learning failure log: data/database/failure_log.json")


if __name__ == "__main__":
    main()
