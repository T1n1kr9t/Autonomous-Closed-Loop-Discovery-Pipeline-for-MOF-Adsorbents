"""Orchestrator for Closed-Loop MOF Adsorbent Discovery Pipeline.

Connects:
LLM Chemist Agent -> RDKit Validator -> PORMAKE Builder -> Zeo++ Screener -> RASPA2 Simulator
with Active Learning Failure Logging and Closed-Loop Feedback.
"""

import json
import logging
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional

from .prompts import DesignTarget, ModificationProposal, FailureFeedbackItem
from .chemist_agents import ChemistAgent
from ..chemistry.rdkit_validator import RDKitValidator
from ..chemistry.pormake_builder import PORMAKEBuilder
from ..screening.zeo_screener import ZeoScreener
from ..simulation.raspa_runner import RASPARunner

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Controls the closed-loop autonomous discovery cycle."""

    def __init__(
        self,
        config_path: str = "config/settings.yaml",
        functional_groups_path: str = "config/functional_groups.json",
        success_db_path: str = "data/database/success_candidates.json",
        failure_db_path: str = "data/database/failure_log.json",
        use_wsl: bool = True
    ):
        self.config_path = Path(config_path)
        self.functional_groups_path = Path(functional_groups_path)
        self.success_db_path = Path(success_db_path)
        self.failure_db_path = Path(failure_db_path)
        self.use_wsl = use_wsl

        # Load configurations
        self.settings = self._load_settings()
        self.functional_groups = self._load_functional_groups()
        self.target = DesignTarget()

        # Extract LLM configurations from settings.yaml
        llm_cfg = self.settings.get("llm", {})
        provider = llm_cfg.get("provider", "auto")
        model = llm_cfg.get("model", None)

        # Initialize sub-modules
        self.chemist_agent = ChemistAgent(provider=provider, model_name=model)
        self.rdkit_validator = RDKitValidator()
        self.pormake_builder = PORMAKEBuilder(use_wsl=use_wsl)
        self.zeo_screener = ZeoScreener(pld_cutoff=self.target.min_pld_angstrom, use_wsl=use_wsl)
        self.raspa_runner = RASPARunner(use_wsl=use_wsl)

        # Database state
        self.successes: List[Dict[str, Any]] = self._load_json(self.success_db_path)
        self.failures: List[Dict[str, Any]] = self._load_json(self.failure_db_path)

    def _load_json(self, path: Path) -> List[Dict[str, Any]]:
        """Load JSON database file or return empty list."""
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
            except Exception:
                return []
        return []

    def _save_json(self, path: Path, data: List[Dict[str, Any]]):
        """Save data list to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_settings(self) -> Dict[str, Any]:
        """Load YAML pipeline settings."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    return data if isinstance(data, dict) else {}
            except Exception as e:
                logger.warning(f"Error reading settings yaml: {e}")
        return {}

    def _load_functional_groups(self) -> List[Dict[str, Any]]:
        """Load functional group pool from config."""
        if self.functional_groups_path.exists():
            try:
                data = json.loads(self.functional_groups_path.read_text(encoding="utf-8"))
                return data.get("functional_groups", [])
            except Exception as e:
                logger.warning(f"Error reading functional groups: {e}")
        return []

    def _get_next_index_for_candidate(
        self,
        candidate_name: str,
        suggested_index: Optional[int] = None
    ) -> int:
        """Find the next available integer index for candidate_name to avoid overwriting existing files."""
        cif_dir = self.pormake_builder.output_dir
        existing_indices = set()

        # 1. Inspect existing CIF files on disk matching candidate_name
        if cif_dir.exists():
            for f in cif_dir.glob(f"{candidate_name}_*.cif"):
                suffix = f.stem[len(candidate_name) + 1:]
                if suffix.isdigit():
                    existing_indices.add(int(suffix))

        # 2. Inspect existing database records
        for record in self.successes:
            if record.get("candidate_name") == candidate_name:
                idx = record.get("candidate_index")
                if isinstance(idx, int):
                    existing_indices.add(idx)
                elif "cif_path" in record:
                    p = Path(record["cif_path"])
                    if p.stem.startswith(f"{candidate_name}_"):
                        suffix = p.stem[len(candidate_name) + 1:]
                        if suffix.isdigit():
                            existing_indices.add(int(suffix))

        for record in self.failures:
            if record.get("candidate_name") == candidate_name:
                idx = record.get("candidate_index")
                if isinstance(idx, int):
                    existing_indices.add(idx)

        # 3. Choose candidate index
        if suggested_index is not None and suggested_index > 0 and suggested_index not in existing_indices:
            candidate_idx = suggested_index
        else:
            candidate_idx = (max(existing_indices) + 1) if existing_indices else 1

        # 4. Final safety check: ensure the CIF file does not already exist on disk
        while (cif_dir / f"{candidate_name}_{candidate_idx}.cif").exists():
            candidate_idx += 1

        return candidate_idx

    def log_failure(
        self,
        candidate_name: str,
        smiles: str,
        stage: str,
        reason: str,
        candidate_index: Optional[int] = None
    ):
        """Record failure to failure log for active learning feedback."""
        record = {
            "candidate_name": candidate_name,
            "candidate_index": candidate_index,
            "smiles": smiles,
            "failure_stage": stage,
            "reason": reason
        }
        self.failures.append(record)
        self._save_json(self.failure_db_path, self.failures)
        logger.info(f"[Active Learning] Logged failure for '{candidate_name}' (idx={candidate_index}) at stage '{stage}': {reason}")

    def log_success(self, entry: Dict[str, Any]):
        """Record successful candidate to database."""
        self.successes.append(entry)
        self._save_json(self.success_db_path, self.successes)
        selectivity_val = entry.get("selectivity_co2_ch4", entry.get("selectivity", "N/A"))
        logger.info(f"[Success Database] Stored candidate '{entry['candidate_name']}' (Selectivity: {selectivity_val})")

    def run_cycle(self, candidate_index: Optional[int] = None) -> Dict[str, Any]:
        """Execute a single closed-loop iteration across all modules."""
        cycle_num = candidate_index if candidate_index is not None else (len(self.successes) + len(self.failures) + 1)
        logger.info(f"=== Starting Cycle #{cycle_num} ===")

        # 1. Chemist Agent proposes modification
        active_failures = [FailureFeedbackItem(**f) for f in self.failures[-5:]] # Pass last 5 failures
        proposal = self.chemist_agent.propose_modification(
            target=self.target,
            allowed_groups=self.functional_groups,
            failures=active_failures
        )
        logger.info(f"[Stage 1 - Agent] Proposed '{proposal.candidate_name}' with SMILES: {proposal.modified_linker_smiles}")

        # Resolve unique candidate index and material name to guarantee CIF files are never overwritten
        actual_index = self._get_next_index_for_candidate(proposal.candidate_name, candidate_index)
        material_name = f"{proposal.candidate_name}_{actual_index}"
        logger.info(f"[Material Target] Assigned identifier '{material_name}' (Index: #{actual_index})")

        # 2. RDKit Validation
        rdkit_res = self.rdkit_validator.validate_smiles(proposal.modified_linker_smiles)
        if not rdkit_res.is_valid:
            self.log_failure(
                proposal.candidate_name,
                proposal.modified_linker_smiles,
                stage="rdkit_validation",
                reason=rdkit_res.error_message or "Valence/Chemical violation",
                candidate_index=actual_index
            )
            return {"status": "failed", "stage": "rdkit_validation", "proposal": proposal.dict(), "error": rdkit_res.error_message}

        logger.info(f"[Stage 2 - RDKit] Validated SMILES (MW: {rdkit_res.molecular_weight:.1f} g/mol)")

        # 3. PORMAKE MOF Assembly
        build_res = self.pormake_builder.build_mof(
            smiles=proposal.modified_linker_smiles,
            material_name=material_name
        )
        if not build_res.success or not build_res.cif_path:
            self.log_failure(
                proposal.candidate_name,
                proposal.modified_linker_smiles,
                stage="pormake_assembly",
                reason=build_res.error_message or "CIF construction failed",
                candidate_index=actual_index
            )
            return {"status": "failed", "stage": "pormake_assembly", "proposal": proposal.dict(), "error": build_res.error_message}

        logger.info(f"[Stage 3 - PORMAKE] Constructed CIF at: {build_res.cif_path} (atoms: {build_res.num_atoms})")

        # 4. Zeo++ Pore Screening
        zeo_res = self.zeo_screener.screen_cif(build_res.cif_path)
        logger.info(f"[Stage 4 - Zeo++] PLD: {zeo_res.pld} A (Cutoff: {self.target.min_pld_angstrom} A) -> Passed: {zeo_res.passed}")
        if not zeo_res.passed:
            self.log_failure(
                proposal.candidate_name,
                proposal.modified_linker_smiles,
                stage="zeo_pore_screening",
                reason=f"Pore blocked (PLD = {zeo_res.pld} A < {self.target.min_pld_angstrom} A threshold)",
                candidate_index=actual_index
            )
            return {
                "status": "failed",
                "stage": "zeo_pore_screening",
                "proposal": proposal.dict(),
                "pld": zeo_res.pld,
                "error": "Pore Limiting Diameter too small for CH4 diffusion"
            }

        # 5. RASPA Adsorption Simulation
        raspa_cfg = self.settings.get("tools", {}).get("raspa", {})
        fast_cycles = raspa_cfg.get("fast_cycles", {})
        sim_cycles = fast_cycles.get("simulation", 2000)
        init_cycles = fast_cycles.get("initialization", 1000)

        sim_res = self.raspa_runner.run_simulation(
            cif_path=build_res.cif_path,
            framework_name=material_name,
            cycles=sim_cycles,
            init_cycles=init_cycles,
            temperature=self.target.temperature_k,
            pressure_pa=self.target.pressure_bar * 1e5,
            y_co2=self.target.co2_fraction,
            y_ch4=self.target.ch4_fraction
        )

        if not sim_res.success:
            self.log_failure(
                proposal.candidate_name,
                proposal.modified_linker_smiles,
                stage="raspa_simulation",
                reason=sim_res.error_message or "Simulation failed",
                candidate_index=actual_index
            )
            return {"status": "failed", "stage": "raspa_simulation", "proposal": proposal.dict(), "error": sim_res.error_message}

        logger.info(
            f"[Stage 5 - RASPA] CO2 Loading: {sim_res.co2_loading_mol_kg} mol/kg | "
            f"CH4 Loading: {sim_res.ch4_loading_mol_kg} mol/kg | "
            f"Selectivity: {sim_res.selectivity_co2_ch4}"
        )

        # Successful candidate entry
        entry = {
            "candidate_name": proposal.candidate_name,
            "candidate_index": actual_index,
            "material_name": material_name,
            "smiles": proposal.modified_linker_smiles,
            "chemical_hypothesis": proposal.chemical_hypothesis,
            "pld_angstrom": zeo_res.pld,
            "co2_loading_mol_kg": sim_res.co2_loading_mol_kg,
            "ch4_loading_mol_kg": sim_res.ch4_loading_mol_kg,
            "selectivity_co2_ch4": sim_res.selectivity_co2_ch4,
            "cif_path": build_res.cif_path,
            "is_mock": sim_res.is_mock or zeo_res.is_mock
        }
        self.log_success(entry)

        return {"status": "success", "candidate": entry}

    def run_discovery_campaign(self, target_successes: int = 3, max_iterations: int = 10) -> List[Dict[str, Any]]:
        """Run iterative campaign until target number of valid candidates found."""
        logger.info(f"Starting discovery campaign: Target {target_successes} candidates (Max trials: {max_iterations})")
        successful_run = []
        iteration = 0

        while len(successful_run) < target_successes and iteration < max_iterations:
            iteration += 1
            logger.info(f"--- Campaign Trial #{iteration}/{max_iterations} ---")
            result = self.run_cycle(candidate_index=None)
            if result.get("status") == "success":
                successful_run.append(result["candidate"])

        logger.info(f"Campaign finished: Discovered {len(successful_run)} high-performance candidates.")
        return successful_run
