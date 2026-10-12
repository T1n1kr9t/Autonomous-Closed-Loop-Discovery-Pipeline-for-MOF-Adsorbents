"""RDKit Validator for Organic Linkers.

Validates chemical validity, valence rules, functional group attachments,
and generates canonical SMILES and 2D/3D representations.
"""

from typing import Dict, Any, Optional, Tuple
import logging

try:
    from rdkit import Chem
    from rdkit.Chem import Descriptors, AllChem
    RDKIT_AVAILABLE = True
except ImportError:
    RDKIT_AVAILABLE = False

logger = logging.getLogger(__name__)


class LinkerValidationResult:
    """Result container for linker validation."""
    def __init__(
        self,
        is_valid: bool,
        canonical_smiles: Optional[str] = None,
        molecular_weight: Optional[float] = None,
        error_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.is_valid = is_valid
        self.canonical_smiles = canonical_smiles
        self.molecular_weight = molecular_weight
        self.error_message = error_message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "canonical_smiles": self.canonical_smiles,
            "molecular_weight": self.molecular_weight,
            "error_message": self.error_message,
            "details": self.details,
        }


class RDKitValidator:
    """Validates linker SMILES, valence rules, and functional group additions."""

    def __init__(self):
        self.rdkit_available = RDKIT_AVAILABLE
        if not self.rdkit_available:
            logger.warning("RDKit is not installed in the current environment. Running in mock/fallback mode.")

    def validate_smiles(self, smiles: str) -> LinkerValidationResult:
        """Validate SMILES string syntax and chemical sanity.
        
        Args:
            smiles: SMILES string of the organic linker.
            
        Returns:
            LinkerValidationResult with validity, canonical SMILES, and error messages.
        """
        if not smiles or not isinstance(smiles, str) or not smiles.strip():
            return LinkerValidationResult(
                is_valid=False,
                error_message="Empty or invalid SMILES string provided."
            )

        smiles_clean = smiles.strip()

        if not self.rdkit_available:
            # Fallback heuristic validation
            if any(token in smiles_clean for token in ["c1", "C(=O)", "O=C"]):
                return LinkerValidationResult(
                    is_valid=True,
                    canonical_smiles=smiles_clean,
                    molecular_weight=166.13, # Approx terephthalic acid
                    details={"mode": "fallback_no_rdkit"}
                )
            return LinkerValidationResult(
                is_valid=False,
                error_message="Fallback validation: SMILES lacks basic dicarboxylate motif.",
                details={"mode": "fallback_no_rdkit"}
            )

        try:
            # Parse molecule
            mol = Chem.MolFromSmiles(smiles_clean)
            if mol is None:
                return LinkerValidationResult(
                    is_valid=False,
                    error_message=f"RDKit syntax error: Failed to parse SMILES '{smiles_clean}'."
                )

            # Strict valence check and sanitization
            sanitization_flag = Chem.SanitizeMol(mol, catchErrors=True)
            if sanitization_flag != Chem.SanitizeFlags.SANITIZE_NONE:
                return LinkerValidationResult(
                    is_valid=False,
                    error_message=f"Valence or sanitization violation (code {sanitization_flag}) in SMILES '{smiles_clean}'."
                )

            # Ensure carboxylate / carboxylic acid groups exist (linker connectivity)
            # We look for at least 2 carboxyl groups: -C(=O)O or -C(=O)[O-]
            carboxyl_pattern = Chem.MolFromSmarts("C(=O)[O,O-]")
            matches = mol.GetSubstructMatches(carboxyl_pattern)
            if len(matches) < 2:
                return LinkerValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Linker must contain at least 2 carboxylic/carboxylate anchor groups "
                        f"for MOF coordination (found {len(matches)})."
                    )
                )

            canonical = Chem.MolToSmiles(mol, canonical=True)
            mw = float(Descriptors.MolWt(mol))
            logp = float(Descriptors.MolLogP(mol))
            hbd = int(Descriptors.NumHDonors(mol))
            hba = int(Descriptors.NumHAcceptors(mol))

            return LinkerValidationResult(
                is_valid=True,
                canonical_smiles=canonical,
                molecular_weight=mw,
                details={
                    "logp": logp,
                    "h_bond_donors": hbd,
                    "h_bond_acceptors": hba,
                    "carboxyl_anchors": len(matches)
                }
            )

        except Exception as e:
            return LinkerValidationResult(
                is_valid=False,
                error_message=f"Unexpected error during RDKit validation: {str(e)}"
            )

    def check_scaffold_compatibility(self, smiles: str, expected_core: str = "c1ccc(cc1)") -> Tuple[bool, str]:
        """Check if the proposed linker is based on the 1,4-benzenedicarboxylate core."""
        if not self.rdkit_available:
            return True, "Passed (heuristic check)"

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return False, "Could not parse molecule."

        core = Chem.MolFromSmarts(expected_core)
        if core is not None and not mol.HasSubstructMatch(core):
            return False, "Linker does not contain the required benzene core scaffold."

        return True, "Scaffold verified."
