"""Chemist Agent Wrapper.

Generates chemical modification proposals via LLM (Gemini / OpenAI / Claude)
or expert heuristic generator when running in offline standalone mode.
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

# Load .env file automatically
try:
    from dotenv import load_dotenv
    # Load .env from project root
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
    else:
        load_dotenv()
except ImportError:
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_path.exists():
        try:
            with open(_env_path, "r", encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k, _v = _k.strip(), _v.strip().strip("'\"")
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v
        except Exception:
            pass

from .prompts import (
    DesignTarget,
    ModificationProposal,
    FailureFeedbackItem,
    CHEMIST_SYSTEM_PROMPT,
    build_agent_user_prompt
)

logger = logging.getLogger(__name__)

# Curated library of innovative candidate proposals for offline / heuristic execution
OFFLINE_CANDIDATE_POOL = [
    {
        "candidate_name": "MOF-5-NH2",
        "base_scaffold": "MOF-5 (Zn4O + BDC, pcu)",
        "modified_linker_smiles": "O=C(O)c1cc(N)ccc1C(=O)O",
        "functional_groups": [
            {
                "group_name": "amino (-NH2)",
                "smiles": "N",
                "position": "2",
                "rationale": "Strong Lewis base site providing electrostatic interaction with quadrupole moment of CO2."
            }
        ],
        "chemical_hypothesis": "Mono-amino substitution significantly boosts CO2 Henry coefficient while maintaining PLD > 7 A."
    },
    {
        "candidate_name": "MOF-5-OH",
        "base_scaffold": "MOF-5 (Zn4O + BDC, pcu)",
        "modified_linker_smiles": "O=C(O)c1cc(O)ccc1C(=O)O",
        "functional_groups": [
            {
                "group_name": "hydroxyl (-OH)",
                "smiles": "O",
                "position": "2",
                "rationale": "Hydrogen-bond donor that polarizes CO2 molecule for enhanced selective binding."
            }
        ],
        "chemical_hypothesis": "Hydroxyl group increases framework dipole moment without reducing pore opening below 3.8 A."
    },
    {
        "candidate_name": "MOF-5-F2",
        "base_scaffold": "MOF-5 (Zn4O + BDC, pcu)",
        "modified_linker_smiles": "c1c(c(cc(c1F)F)C(=O)O)C(=O)O",
        "functional_groups": [
            {
                "group_name": "difluoro (-F2)",
                "smiles": "F",
                "position": "2,5",
                "rationale": "Fluorination increases framework hydrophobicity and enhances CO2-framework dispersion interactions."
            }
        ],
        "chemical_hypothesis": "Fluorine atoms create localized charge gradients favoring quadrupole CO2 over nonpolar CH4."
    },
    {
        "candidate_name": "MOF-5-Cl2",
        "base_scaffold": "MOF-5 (Zn4O + BDC, pcu)",
        "modified_linker_smiles": "c1c(c(cc(c1Cl)Cl)C(=O)O)C(=O)O",
        "functional_groups": [
            {
                "group_name": "dichloro (-Cl2)",
                "smiles": "Cl",
                "position": "2,5",
                "rationale": "Modulates pore aperture while providing polarizable halogen interaction sites."
            }
        ],
        "chemical_hypothesis": "Chlorine substitution slightly constricts the pore window, enhancing kinetic sieving of CO2 (3.3 A) over CH4 (3.8 A)."
    },
    {
        "candidate_name": "MOF-5-NO2",
        "base_scaffold": "MOF-5 (Zn4O + BDC, pcu)",
        "modified_linker_smiles": "O=C(O)c1cc([N+](=O)[O-])ccc1C(=O)O",
        "functional_groups": [
            {
                "group_name": "nitro (-NO2)",
                "smiles": "[N+](=O)[O-]",
                "position": "2",
                "rationale": "Strong electron withdrawing group generating large localized dipole."
            }
        ],
        "chemical_hypothesis": "Nitro functionality increases isosteric heat of adsorption for CO2."
    }
]


class ChemistAgent:
    """Agent that proposes linker modifications based on targets and failure history."""

    def __init__(
        self,
        provider: str = "auto", # 'gemini', 'openai', 'offline'
        model_name: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        self.provider = provider
        self.model_name = model_name or os.environ.get("GEMINI_MODEL") or "gemini-3.6-flash"
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self._offline_index = 0

    def propose_modification(
        self,
        target: DesignTarget,
        allowed_groups: List[Dict[str, Any]],
        failures: List[FailureFeedbackItem]
    ) -> ModificationProposal:
        """Generate a modification proposal."""
        active_key = self.api_key or os.environ.get("GEMINI_API_KEY")
        is_placeholder = not active_key or active_key.startswith("your_") or len(active_key) < 10

        # Check if LLM API is available and requested
        if self.provider in ["gemini", "auto"] and not is_placeholder:
            try:
                return self._call_gemini(target, allowed_groups, failures)
            except Exception as e:
                logger.warning(f"Gemini API call failed: {e}. Falling back to heuristic pool.")

        # Standalone / Offline generator
        return self._propose_from_pool(failures)

    def _call_gemini(
        self,
        target: DesignTarget,
        allowed_groups: List[Dict[str, Any]],
        failures: List[FailureFeedbackItem]
    ) -> ModificationProposal:
        """Call Gemini API with structured JSON output."""
        import google.generativeai as genai
        active_key = self.api_key or os.environ.get("GEMINI_API_KEY")
        genai.configure(api_key=active_key)
        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=CHEMIST_SYSTEM_PROMPT,
            generation_config={"response_mime_type": "application/json"}
        )

        user_content = build_agent_user_prompt(target, allowed_groups, failures)
        response = model.generate_content(user_content)
        data = json.loads(response.text)
        return ModificationProposal(**data)

    def _propose_from_pool(self, failures: List[FailureFeedbackItem]) -> ModificationProposal:
        """Select innovative candidate from curated pool while avoiding past failures."""
        failed_smiles = {f.smiles for f in failures}

        # Filter candidates that haven't failed yet
        candidates = [c for c in OFFLINE_CANDIDATE_POOL if c["modified_linker_smiles"] not in failed_smiles]

        if not candidates:
            # If all standard candidates explored, generate modified variant
            idx = len(failures) + 1
            return ModificationProposal(
                candidate_name=f"MOF-5-MultiSub-{idx}",
                base_scaffold="MOF-5 (Zn4O + BDC, pcu)",
                modified_linker_smiles="O=C(O)c1cc(N)c(F)cc1C(=O)O",
                functional_groups=[
                    {"group_name": "amino (-NH2)", "smiles": "N", "position": "2", "rationale": "Polar affinity"},
                    {"group_name": "fluoro (-F)", "smiles": "F", "position": "3", "rationale": "Pore tuning"}
                ],
                chemical_hypothesis="Dual functionalization with NH2 and F balances polarity and pore size."
            )

        chosen = candidates[self._offline_index % len(candidates)]
        self._offline_index += 1
        return ModificationProposal(**chosen)
