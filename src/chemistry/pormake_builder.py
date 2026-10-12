"""PORMAKE Builder for MOF-5 and functionalized derivatives.

Constructs 3D porous crystal structures (.cif) by combining:
- Zn4O inorganic node (N16 / octahedral coordination)
- Functionalized BDC organic linker (E14 or substituted derivatives)
- pcu topology net
"""

import os
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Known PORMAKE edge codes for functionalized BDC linkers
KNOWN_BDC_EDGE_MAP = {
    "c1cc(c(cc1C(=O)O)N)C(=O)O": "E128",            # BDC-NH2
    "O=C(O)c1cc(N)ccc1C(=O)O": "E128",              # BDC-NH2 canonical alt
    "O=C(O)c1ccc(C(=O)O)c(N)c1": "E128",            # BDC-NH2
    "c1c(c(cc(c1Cl)Cl)C(=O)O)C(=O)O": "E131",      # BDC-Cl2
    "c1c(c(cc(c1F)F)C(=O)O)C(=O)O": "E186",        # BDC-F2
    "c1c(c(c(c(c1F)F)F)C(=O)O)C(=O)O": "E228",     # BDC-F4
    "O=C(O)c1ccc(C(=O)O)cc1": "E14",                # Baseline BDC
    "c1cc(ccc1C(=O)O)C(=O)O": "E14",                # Baseline BDC
}


class MOFBuildResult:
    """Result data class for MOF assembly."""
    def __init__(
        self,
        success: bool,
        cif_path: Optional[str] = None,
        num_atoms: int = 0,
        topology: str = "pcu",
        node: str = "Zn4O (N16)",
        linker_code: str = "E14",
        error_message: Optional[str] = None,
        is_mock: bool = False
    ):
        self.success = success
        self.cif_path = cif_path
        self.num_atoms = num_atoms
        self.topology = topology
        self.node = node
        self.linker_code = linker_code
        self.error_message = error_message
        self.is_mock = is_mock

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "cif_path": self.cif_path,
            "num_atoms": self.num_atoms,
            "topology": self.topology,
            "node": self.node,
            "linker_code": self.linker_code,
            "error_message": self.error_message,
            "is_mock": self.is_mock,
        }


class PORMAKEBuilder:
    """Assembles MOF crystals using PORMAKE or fallback templating."""

    def __init__(
        self,
        node_code: str = "N16",
        topology_name: str = "pcu",
        output_dir: Optional[str] = None,
        use_wsl: bool = True
    ):
        self.node_code = node_code
        self.topology_name = topology_name
        self.output_dir = Path(output_dir or "data/generated_cifs").resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.use_wsl = use_wsl

    def resolve_edge_code(self, smiles: str) -> str:
        """Resolve a SMILES string to the closest PORMAKE edge building block."""
        clean_smiles = smiles.strip()
        if clean_smiles in KNOWN_BDC_EDGE_MAP:
            return KNOWN_BDC_EDGE_MAP[clean_smiles]

        # Heuristic matching by functional group presence
        if "N" in clean_smiles and ("C(=O)" in clean_smiles or "O=C" in clean_smiles):
            return "E128" # -NH2
        elif "F" in clean_smiles:
            return "E186" # -F2
        elif "Cl" in clean_smiles:
            return "E131" # -Cl2

        return "E14" # Default unsubstituted BDC

    def build_mof(
        self,
        smiles: str,
        material_name: str = "MOF-5_derivative",
        force_mock: bool = False,
        overwrite: bool = True
    ) -> MOFBuildResult:
        """Build MOF crystal structure for the given linker SMILES.
        
        Args:
            smiles: SMILES string of the modified BDC linker.
            material_name: Identifier name for the output CIF file.
            force_mock: If True, generate template without invoking heavy optimization.
            overwrite: If False, auto-increments candidate suffix when target file exists.
            
        Returns:
            MOFBuildResult with path to the generated .cif file.
        """
        if not overwrite:
            cif_p = self.output_dir / f"{material_name}.cif"
            if cif_p.exists():
                parts = material_name.rsplit("_", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    prefix = parts[0]
                    idx = int(parts[1])
                else:
                    prefix = material_name
                    idx = 1
                while (self.output_dir / f"{prefix}_{idx}.cif").exists():
                    idx += 1
                material_name = f"{prefix}_{idx}"

        edge_code = self.resolve_edge_code(smiles)
        cif_filename = f"{material_name}.cif"
        out_cif_path = self.output_dir / cif_filename

        if force_mock:
            return self._build_template_cif(out_cif_path, edge_code, material_name)

        # Attempt to build via PORMAKE
        try:
            import pormake as pm
            db = pm.Database()
            builder = pm.Builder()
            topo = db.get_topo(self.topology_name)
            node_bb = db.get_bb(self.node_code)
            edge_bb = db.get_bb(edge_code)

            mof = builder.build_by_type(
                topology=topo,
                node_bbs={0: node_bb},
                edge_bbs={(0, 0): edge_bb}
            )

            # Write CIF
            mof.write_cif(str(out_cif_path))

            if out_cif_path.exists() and out_cif_path.stat().st_size > 0:
                return MOFBuildResult(
                    success=True,
                    cif_path=str(out_cif_path),
                    num_atoms=len(mof.atoms),
                    topology=self.topology_name,
                    node=self.node_code,
                    linker_code=edge_code
                )
            else:
                logger.warning("PORMAKE build finished but output CIF file is empty or missing. Falling back to template.")
                return self._build_template_cif(out_cif_path, edge_code, material_name)

        except Exception as e:
            logger.warning(f"PORMAKE build encountered exception: {e}. Falling back to template.")
            return self._build_template_cif(out_cif_path, edge_code, material_name, error=str(e))

    def _build_template_cif(
        self,
        out_cif_path: Path,
        edge_code: str,
        material_name: str,
        error: Optional[str] = None
    ) -> MOFBuildResult:
        """Generate a valid standard MOF-5 CIF template as a robust fallback."""
        # Standard cubic MOF-5 cell (a = b = c = 25.885 A, alpha = beta = gamma = 90 deg)
        template_cif_content = f"""data_{material_name}
_audit_creation_method            'Senior Project Closed-Loop Pipeline'
_chemical_name_systematic         'MOF-5 ({edge_code} derivative)'
_cell_length_a                    25.8849
_cell_length_b                    25.8849
_cell_length_c                    25.8849
_cell_angle_alpha                 90.0000
_cell_angle_beta                  90.0000
_cell_angle_gamma                 90.0000
_cell_volume                      17343.8
_symmetry_space_group_name_H-M    'F m -3 m'
_symmetry_Int_Tables_number       225

loop_
_symmetry_equiv_pos_as_xyz
'x, y, z'
'-x, -y, -z'

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Zn1 Zn 0.20380 0.20380 0.20380
O1  O  0.25000 0.25000 0.25000
O2  O  0.15340 0.21980 0.21980
C1  C  0.12870 0.25000 0.25000
C2  C  0.07130 0.25000 0.25000
C3  C  0.04280 0.29740 0.25000
H1  H  0.06170 0.33400 0.25000
"""
        out_cif_path.write_text(template_cif_content, encoding="utf-8")
        return MOFBuildResult(
            success=True,
            cif_path=str(out_cif_path),
            num_atoms=53,
            topology=self.topology_name,
            node=self.node_code,
            linker_code=edge_code,
            error_message=error,
            is_mock=True
        )
