"""RASPA2 simulation.input Generator.

Generates simulation.input configuration files for Grand Canonical Monte Carlo (GCMC)
binary mixture adsorption (CO2 / CH4) in MOFs.
"""

from typing import Dict, Any, Optional
from pathlib import Path


class RASPAGenerator:
    """Generates simulation.input file for RASPA GCMC simulations."""

    def __init__(
        self,
        default_cycles: int = 2000,
        default_init_cycles: int = 1000,
        temperature: float = 298.15,
        pressure_pa: float = 1.0e5, # 1 bar
        co2_mol_fraction: float = 0.50,
        ch4_mol_fraction: float = 0.50,
        forcefield: str = "Dubbeldam2007FlexibleIRMOF-1"
    ):
        self.default_cycles = default_cycles
        self.default_init_cycles = default_init_cycles
        self.temperature = temperature
        self.pressure_pa = pressure_pa
        self.co2_mol_fraction = co2_mol_fraction
        self.ch4_mol_fraction = ch4_mol_fraction
        self.forcefield = forcefield

    def generate_input(
        self,
        framework_name: str,
        output_path: Optional[str] = None,
        cycles: Optional[int] = None,
        init_cycles: Optional[int] = None,
        temperature: Optional[float] = None,
        pressure_pa: Optional[float] = None,
        co2_mol_fraction: Optional[float] = None,
        ch4_mol_fraction: Optional[float] = None,
        helium_void_fraction: float = 0.81
    ) -> str:
        """Create simulation.input string content and optionally write to file.
        
        Args:
            framework_name: Name of the MOF structure (without .cif).
            output_path: Optional path to write simulation.input.
            cycles: Simulation production cycles (e.g. 2,000 for fast screening).
            init_cycles: Initialization cycles (e.g. 1,000).
            temperature: System temperature in K.
            pressure_pa: External pressure in Pascals (e.g. 1e5 for 1 bar).
            co2_mol_fraction: Bulk mole fraction of CO2.
            ch4_mol_fraction: Bulk mole fraction of CH4.
            helium_void_fraction: MOF framework void fraction.
            
        Returns:
            String content of simulation.input.
        """
        n_cycles = cycles or self.default_cycles
        n_init = init_cycles or self.default_init_cycles
        temp_k = temperature or self.temperature
        p_pa = pressure_pa or self.pressure_pa
        y_co2 = co2_mol_fraction if co2_mol_fraction is not None else self.co2_mol_fraction
        y_ch4 = ch4_mol_fraction if ch4_mol_fraction is not None else self.ch4_mol_fraction

        print_freq = max(100, n_cycles // 4)

        content = f"""SimulationType                MonteCarlo
NumberOfCycles                {n_cycles}
NumberOfInitializationCycles  {n_init}
PrintEvery                    {print_freq}

Forcefield                    {self.forcefield}

Framework 0
FrameworkName {framework_name}
UnitCells 1 1 1
HeliumVoidFraction {helium_void_fraction:.2f}
ExternalTemperature {temp_k:.2f}
ExternalPressure  {p_pa:.1e}

Component 0 MoleculeName               CO2
            MoleculeDefinition         ExampleDefinitions
            MolFraction                {y_co2:.4f}
            TranslationProbability     0.5
            ReinsertionProbability     0.5
            IdentityChangeProbability  1.0
              NumberOfIdentityChanges  2
              IdentityChangesList      0 1
            SwapProbability            1.0
            CreateNumberOfMolecules    0

Component 1 MoleculeName               methane
            MoleculeDefinition         ExampleDefinitions
            MolFraction                {y_ch4:.4f}
            TranslationProbability     0.5
            ReinsertionProbability     0.5
            IdentityChangeProbability  1.0
              NumberOfIdentityChanges  2
              IdentityChangesList      0 1
            SwapProbability            1.0
            CreateNumberOfMolecules    0
"""
        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        return content
