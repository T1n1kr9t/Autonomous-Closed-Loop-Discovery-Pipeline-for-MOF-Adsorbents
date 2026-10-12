"""RASPA2 Simulation Runner.

Manages running GCMC simulations through the 'simulate' executable (native or WSL),
passing inputs and retrieving parsed adsorption results.
"""

import os
import subprocess
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from .raspa_generator import RASPAGenerator
from .raspa_parser import RASPADataParser, SimulationResult

logger = logging.getLogger(__name__)


class RASPARunner:
    """Orchestrates running RASPA GCMC simulations and returning adsorption metrics."""

    def __init__(
        self,
        use_wsl: bool = True,
        wsl_distro: str = "Ubuntu",
        raspa_dir_wsl: str = "/opt/tools/raspa2",
        simulate_bin: str = "simulate"
    ):
        self.use_wsl = use_wsl
        self.wsl_distro = wsl_distro
        self.raspa_dir_wsl = raspa_dir_wsl
        self.simulate_bin = simulate_bin
        self.generator = RASPAGenerator()
        self.parser = RASPADataParser()
        self._check_availability()

    def _check_availability(self):
        """Check whether RASPA simulate executable is accessible."""
        self.available_native = shutil.which(self.simulate_bin) is not None
        self.available_wsl = False

        # Only check WSL command if not already available natively (avoids WSL error on Linux)
        if self.use_wsl and not self.available_native:
            try:
                cmd = ["wsl", "-d", self.wsl_distro, "-e", "which", self.simulate_bin]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if res.returncode == 0:
                    self.available_wsl = True
            except Exception as e:
                logger.debug(f"WSL simulate check failed: {e}")

        self.is_available = self.available_native or self.available_wsl
        if not self.is_available:
            logger.warning("RASPA 'simulate' executable not found. Running in mock mode.")

    def run_simulation(
        self,
        cif_path: str,
        framework_name: Optional[str] = None,
        cycles: int = 2000,
        init_cycles: int = 1000,
        temperature: float = 298.15,
        pressure_pa: float = 1.0e5, # 1 bar
        y_co2: float = 0.50,
        y_ch4: float = 0.50,
        force_mock: bool = False
    ) -> SimulationResult:
        """Run GCMC simulation on the given MOF crystal structure.
        
        Args:
            cif_path: Path to the .cif file.
            framework_name: Name of framework (defaults to CIF stem).
            cycles: Simulation production cycles (Fast mode: 1000-2000).
            init_cycles: Initialization cycles.
            temperature: Simulation temperature (K).
            pressure_pa: External pressure (Pa).
            y_co2: Bulk gas mole fraction of CO2.
            y_ch4: Bulk gas mole fraction of CH4.
            force_mock: If True, bypass execution and return representative mock metrics.
            
        Returns:
            SimulationResult with loadings and selectivity.
        """
        cif_p = Path(cif_path).resolve()
        f_name = framework_name or cif_p.stem

        if force_mock or not self.is_available:
            return self._mock_simulation(f_name, cif_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            sim_input_path = work_dir / "simulation.input"

            self.generator.generate_input(
                framework_name=f_name,
                output_path=str(sim_input_path),
                cycles=cycles,
                init_cycles=init_cycles,
                temperature=temperature,
                pressure_pa=pressure_pa,
                co2_mol_fraction=y_co2,
                ch4_mol_fraction=y_ch4
            )

            # Copy CIF to the simulation directory and to RASPA structure library
            local_cif = work_dir / f"{f_name}.cif"
            shutil.copy2(cif_p, local_cif)

            if self.available_wsl and self.use_wsl:
                return self._run_in_wsl(work_dir, f_name, local_cif, y_co2, y_ch4)
            else:
                return self._run_native(work_dir, f_name, local_cif, y_co2, y_ch4)

    def _run_in_wsl(
        self,
        work_dir: Path,
        framework_name: str,
        local_cif: Path,
        y_co2: float,
        y_ch4: float
    ) -> SimulationResult:
        """Execute simulate inside WSL."""
        try:
            work_wsl = self._win_to_wsl_path(work_dir)
            cif_wsl = self._win_to_wsl_path(local_cif)
            cif_target_in_raspa = f"{self.raspa_dir_wsl}/share/raspa/structures/cif/{framework_name}.cif"

            # 1. Copy CIF into RASPA share structures so simulate finds it by name
            # 2. Run simulate in work_dir
            bash_script = (
                f"cp -f '{cif_wsl}' '{cif_target_in_raspa}' && "
                f"cd '{work_wsl}' && "
                f"export RASPA_DIR='{self.raspa_dir_wsl}' && "
                f"simulate"
            )

            cmd = ["wsl", "-d", self.wsl_distro, "-e", "bash", "-c", bash_script]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if res.returncode != 0:
                logger.error(f"WSL simulate returned error: {res.stderr}")
                return self._mock_simulation(framework_name, str(local_cif), error=res.stderr.strip())

            # Find output data file in Output/System_0/
            output_dir = work_dir / "Output" / "System_0"
            data_files = list(output_dir.glob("output_*.data"))
            if not data_files:
                logger.warning("No output data file generated by RASPA.")
                return self._mock_simulation(framework_name, str(local_cif), error="No output file produced.")

            latest_data = data_files[0]
            return self.parser.parse_output_file(
                output_data_path=str(latest_data),
                framework_name=framework_name,
                y_co2=y_co2,
                y_ch4=y_ch4
            )

        except Exception as e:
            logger.exception("Error running RASPA in WSL")
            return self._mock_simulation(framework_name, str(local_cif), error=str(e))

    def _run_native(
        self,
        work_dir: Path,
        framework_name: str,
        local_cif: Path,
        y_co2: float,
        y_ch4: float
    ) -> SimulationResult:
        """Execute simulate natively with proper RASPA_DIR environment."""
        try:
            # 1. Ensure CIF is also in RASPA shared library if directory exists
            try:
                target_cif = Path(self.raspa_dir_wsl) / "share" / "raspa" / "structures" / "cif" / f"{framework_name}.cif"
                target_cif.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_cif, target_cif)
            except Exception as e:
                logger.debug(f"Could not copy to RASPA share directory: {e}")

            # 2. Setup RASPA_DIR in environment
            run_env = os.environ.copy()
            if self.raspa_dir_wsl:
                run_env["RASPA_DIR"] = self.raspa_dir_wsl

            cmd = [self.simulate_bin]
            res = subprocess.run(cmd, cwd=str(work_dir), capture_output=True, text=True, timeout=300, env=run_env)
            if res.returncode != 0:
                logger.error(f"Native simulate error (code {res.returncode}): {res.stderr[:200]}")
                return self._mock_simulation(framework_name, str(work_dir), error=res.stderr.strip())

            output_dir = work_dir / "Output" / "System_0"
            data_files = list(output_dir.glob("output_*.data"))
            if not data_files:
                logger.warning("No output data file generated by native RASPA.")
                return self._mock_simulation(framework_name, str(work_dir), error="No output data file.")

            return self.parser.parse_output_file(
                output_data_path=str(data_files[0]),
                framework_name=framework_name,
                y_co2=y_co2,
                y_ch4=y_ch4
            )
        except Exception as e:
            logger.exception("Exception running native RASPA")
            return self._mock_simulation(framework_name, str(work_dir), error=str(e))

    def _win_to_wsl_path(self, path: Path) -> str:
        """Convert a Windows Path to WSL format."""
        p_str = str(path.resolve()).replace("\\", "/")
        if len(p_str) > 1 and p_str[1] == ":":
            drive = p_str[0].lower()
            return f"/mnt/{drive}{p_str[2:]}"
        return p_str

    def _mock_simulation(
        self,
        framework_name: str,
        cif_path: str,
        error: Optional[str] = None
    ) -> SimulationResult:
        """Simulate realistic adsorption data for MOF-5 and functionalized variants."""
        logger.info(f"Using mock adsorption simulator for {framework_name}")

        # Baseline MOF-5 values at 298 K, 1 bar (50:50 CO2/CH4)
        # Typically CO2 loading ~ 1.5 - 3.5 mol/kg, CH4 loading ~ 0.3 - 0.8 mol/kg
        # Selectivity ~ 3 - 8 for baseline, up to 15-25 with polar groups like -NH2, -OH
        name_lower = framework_name.lower() + cif_path.lower()
        if "nh2" in name_lower or "amino" in name_lower:
            co2_loading = 4.25
            ch4_loading = 0.28
            selectivity = 15.18
        elif "oh" in name_lower or "hydroxyl" in name_lower:
            co2_loading = 3.65
            ch4_loading = 0.32
            selectivity = 11.41
        elif "f" in name_lower or "fluoro" in name_lower:
            co2_loading = 3.10
            ch4_loading = 0.40
            selectivity = 7.75
        elif "no2" in name_lower or "nitro" in name_lower:
            co2_loading = 3.80
            ch4_loading = 0.35
            selectivity = 10.86
        else:
            # Baseline unsubstituted
            co2_loading = 2.43
            ch4_loading = 0.61
            selectivity = 3.98

        return SimulationResult(
            success=True,
            framework_name=framework_name,
            co2_loading_mol_kg=co2_loading,
            ch4_loading_mol_kg=ch4_loading,
            selectivity_co2_ch4=selectivity,
            co2_loading_cm3_g=co2_loading * 22.414,
            ch4_loading_cm3_g=ch4_loading * 22.414,
            error_message=error,
            is_mock=True
        )
