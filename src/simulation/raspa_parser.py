"""RASPA2 Output Parser.

Parses GCMC output data files (Output/System_0/output_*.data) to extract:
- CO2 loading (mol/kg, cm3 STP/g)
- CH4 loading (mol/kg, cm3 STP/g)
- Adsorption Selectivity S(CO2/CH4)
"""

import re
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class SimulationResult:
    """Container for parsed adsorption simulation results."""
    def __init__(
        self,
        success: bool,
        framework_name: str,
        co2_loading_mol_kg: float = 0.0,
        ch4_loading_mol_kg: float = 0.0,
        selectivity_co2_ch4: float = 0.0,
        co2_loading_cm3_g: float = 0.0,
        ch4_loading_cm3_g: float = 0.0,
        raw_output_file: Optional[str] = None,
        error_message: Optional[str] = None,
        is_mock: bool = False
    ):
        self.success = success
        self.framework_name = framework_name
        self.co2_loading_mol_kg = round(co2_loading_mol_kg, 4)
        self.ch4_loading_mol_kg = round(ch4_loading_mol_kg, 4)
        self.selectivity_co2_ch4 = round(selectivity_co2_ch4, 2)
        self.co2_loading_cm3_g = round(co2_loading_cm3_g, 2)
        self.ch4_loading_cm3_g = round(ch4_loading_cm3_g, 2)
        self.raw_output_file = raw_output_file
        self.error_message = error_message
        self.is_mock = is_mock

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "framework_name": self.framework_name,
            "co2_loading_mol_kg": self.co2_loading_mol_kg,
            "ch4_loading_mol_kg": self.ch4_loading_mol_kg,
            "selectivity_co2_ch4": self.selectivity_co2_ch4,
            "co2_loading_cm3_g": self.co2_loading_cm3_g,
            "ch4_loading_cm3_g": self.ch4_loading_cm3_g,
            "raw_output_file": self.raw_output_file,
            "error_message": self.error_message,
            "is_mock": self.is_mock
        }


class RASPADataParser:
    """Parses RASPA2 output files."""

    @staticmethod
    def parse_output_file(
        output_data_path: str,
        framework_name: str = "MOF",
        y_co2: float = 0.50,
        y_ch4: float = 0.50
    ) -> SimulationResult:
        """Parse a single output_*.data file from RASPA.
        
        Args:
            output_data_path: Path to the .data output file.
            framework_name: Identifier name for the MOF.
            y_co2: Mole fraction of CO2 in bulk feed.
            y_ch4: Mole fraction of CH4 in bulk feed.
            
        Returns:
            SimulationResult with loadings and selectivity.
        """
        p = Path(output_data_path)
        if not p.exists():
            return SimulationResult(
                success=False,
                framework_name=framework_name,
                error_message=f"Output file does not exist: {output_data_path}"
            )

        content = p.read_text(encoding="utf-8", errors="ignore")

        # Regex patterns to capture component loadings
        # Average loading absolute [mol/kg framework]                  X.XXXXX +/-       Y.YYYYY [-]
        pattern_mol_kg = re.compile(
            r"Average loading absolute \[mol/kg framework\]\s+([\d\.\-]+)\s+\+/\-",
            re.IGNORECASE
        )
        pattern_cm3_g = re.compile(
            r"Average loading absolute \[cm\^3 \(STP\)/gr framework\]\s+([\d\.\-]+)\s+\+/\-",
            re.IGNORECASE
        )

        matches_mol_kg = pattern_mol_kg.findall(content)
        matches_cm3_g = pattern_cm3_g.findall(content)

        if len(matches_mol_kg) >= 2:
            try:
                co2_mol_kg = float(matches_mol_kg[0])
                ch4_mol_kg = float(matches_mol_kg[1])

                co2_cm3_g = float(matches_cm3_g[0]) if len(matches_cm3_g) >= 1 else co2_mol_kg * 22.414
                ch4_cm3_g = float(matches_cm3_g[1]) if len(matches_cm3_g) >= 2 else ch4_mol_kg * 22.414

                # Calculate selectivity: S = (q_CO2 / q_CH4) / (y_CO2 / y_CH4)
                if ch4_mol_kg > 1e-6 and y_co2 > 0 and y_ch4 > 0:
                    selectivity = (co2_mol_kg / ch4_mol_kg) / (y_co2 / y_ch4)
                elif co2_mol_kg > 0:
                    selectivity = 999.0 # Very high selectivity
                else:
                    selectivity = 1.0

                return SimulationResult(
                    success=True,
                    framework_name=framework_name,
                    co2_loading_mol_kg=co2_mol_kg,
                    ch4_loading_mol_kg=ch4_mol_kg,
                    selectivity_co2_ch4=selectivity,
                    co2_loading_cm3_g=co2_cm3_g,
                    ch4_loading_cm3_g=ch4_cm3_g,
                    raw_output_file=str(p)
                )

            except ValueError as e:
                return SimulationResult(
                    success=False,
                    framework_name=framework_name,
                    error_message=f"Failed to parse float values from output: {e}"
                )

        return SimulationResult(
            success=False,
            framework_name=framework_name,
            error_message="Could not find loading data for both CO2 and CH4 in output."
        )
