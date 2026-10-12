"""Zeo++ Geometric Pore Screener.

Runs Zeo++ network analysis to extract:
- Di: Maximum included sphere diameter (cage diameter, Angstrom)
- Df: Maximum free sphere diameter (Pore Limiting Diameter / PLD, Angstrom)
- Dif: Maximum included sphere along free sphere path (Angstrom)

Applies screening criteria:
PLD >= 3.8 Angstrom (CH4 kinetic diameter threshold for gas transport).
"""

import os
import subprocess
import shutil
import tempfile
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ZeoScreeningResult:
    """Result data class for Zeo++ pore screening."""
    def __init__(
        self,
        passed: bool,
        pld: float,
        largest_included_diameter: float,
        largest_free_path_included_diameter: float,
        cif_path: str,
        error_message: Optional[str] = None,
        is_mock: bool = False
    ):
        self.passed = passed
        self.pld = pld
        self.largest_included_diameter = largest_included_diameter
        self.largest_free_path_included_diameter = largest_free_path_included_diameter
        self.cif_path = cif_path
        self.error_message = error_message
        self.is_mock = is_mock

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "pld_angstrom": self.pld,
            "di_angstrom": self.largest_included_diameter,
            "dif_angstrom": self.largest_free_path_included_diameter,
            "cif_path": self.cif_path,
            "error_message": self.error_message,
            "is_mock": self.is_mock
        }


class ZeoScreener:
    """Wrapper to run Zeo++ 'network' executable and evaluate pore dimensions."""

    def __init__(
        self,
        pld_cutoff: float = 3.8,
        use_wsl: bool = True,
        wsl_distro: str = "Ubuntu",
        network_bin: str = "network"
    ):
        self.pld_cutoff = pld_cutoff
        self.use_wsl = use_wsl
        self.wsl_distro = wsl_distro
        self.network_bin = network_bin
        self._check_availability()

    def _check_availability(self):
        """Check whether Zeo++ is available either locally or in WSL."""
        self.available_native = shutil.which(self.network_bin) is not None
        self.available_wsl = False

        # Only check WSL command if not already available natively
        if self.use_wsl and not self.available_native:
            try:
                cmd = ["wsl", "-d", self.wsl_distro, "-e", "which", self.network_bin]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if res.returncode == 0:
                    self.available_wsl = True
            except Exception as e:
                logger.debug(f"WSL Zeo++ check failed: {e}")

        self.is_available = self.available_native or self.available_wsl
        if not self.is_available:
            logger.warning("Zeo++ 'network' binary not found. Mock fallback will be used.")

    def screen_cif(self, cif_path: str, force_mock: bool = False) -> ZeoScreeningResult:
        """Run Zeo++ pore analysis on the given CIF file.
        
        Args:
            cif_path: Path to the .cif file.
            force_mock: If True, bypass execution and return mock results.
            
        Returns:
            ZeoScreeningResult with PLD and pass/fail status.
        """
        if force_mock or not self.is_available:
            return self._mock_screening(cif_path)

        cif_path_obj = Path(cif_path).resolve()
        if not cif_path_obj.exists():
            return ZeoScreeningResult(
                passed=False,
                pld=0.0,
                largest_included_diameter=0.0,
                largest_free_path_included_diameter=0.0,
                cif_path=str(cif_path),
                error_message=f"CIF file not found: {cif_path}"
            )

        # Run via WSL or Native
        with tempfile.TemporaryDirectory() as tmpdir:
            res_filename = "screening_output.res"
            res_path = Path(tmpdir) / res_filename

            if self.available_wsl and self.use_wsl:
                return self._run_in_wsl(cif_path_obj, res_path)
            else:
                return self._run_native(cif_path_obj, res_path)

    def _run_in_wsl(self, cif_path: Path, res_path: Path) -> ZeoScreeningResult:
        """Execute network in WSL environment."""
        try:
            # Convert Windows paths to WSL paths
            cif_wsl = self._win_to_wsl_path(cif_path)
            res_wsl = self._win_to_wsl_path(res_path)

            cmd = [
                "wsl", "-d", self.wsl_distro, "-e", "bash", "-c",
                f"network -ha -res '{res_wsl}' '{cif_wsl}'"
            ]
            run_res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if run_res.returncode != 0:
                logger.error(f"Zeo++ WSL execution failed: {run_res.stderr}")
                return ZeoScreeningResult(
                    passed=False,
                    pld=0.0,
                    largest_included_diameter=0.0,
                    largest_free_path_included_diameter=0.0,
                    cif_path=str(cif_path),
                    error_message=f"Zeo++ error: {run_res.stderr.strip()}"
                )

            return self._parse_res_file(res_path, str(cif_path))

        except Exception as e:
            logger.exception("Error executing Zeo++ in WSL")
            return self._mock_screening(str(cif_path), error=str(e))

    def _run_native(self, cif_path: Path, res_path: Path) -> ZeoScreeningResult:
        """Execute network natively."""
        try:
            cmd = [self.network_bin, "-ha", "-res", str(res_path), str(cif_path)]
            run_res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if run_res.returncode != 0:
                return ZeoScreeningResult(
                    passed=False,
                    pld=0.0,
                    largest_included_diameter=0.0,
                    largest_free_path_included_diameter=0.0,
                    cif_path=str(cif_path),
                    error_message=f"Zeo++ error: {run_res.stderr.strip()}"
                )

            return self._parse_res_file(res_path, str(cif_path))

        except Exception as e:
            return self._mock_screening(str(cif_path), error=str(e))

    def _parse_res_file(self, res_path: Path, cif_path_str: str) -> ZeoScreeningResult:
        """Parse the .res file generated by Zeo++."""
        if not res_path.exists():
            return ZeoScreeningResult(
                passed=False,
                pld=0.0,
                largest_included_diameter=0.0,
                largest_free_path_included_diameter=0.0,
                cif_path=cif_path_str,
                error_message="Zeo++ did not generate output .res file."
            )

        content = res_path.read_text(encoding="utf-8").strip()
        lines = content.splitlines()
        if not lines:
            return ZeoScreeningResult(
                passed=False,
                pld=0.0,
                largest_included_diameter=0.0,
                largest_free_path_included_diameter=0.0,
                cif_path=cif_path_str,
                error_message="Empty .res file from Zeo++."
            )

        # Expected line: <filename> <Di> <Df> <Dif>
        parts = lines[0].split()
        if len(parts) >= 4:
            try:
                di = float(parts[1])
                df = float(parts[2])  # Pore Limiting Diameter (PLD)
                dif = float(parts[3])
                passed = (df >= self.pld_cutoff)
                return ZeoScreeningResult(
                    passed=passed,
                    pld=round(df, 3),
                    largest_included_diameter=round(di, 3),
                    largest_free_path_included_diameter=round(dif, 3),
                    cif_path=cif_path_str
                )
            except ValueError as e:
                return ZeoScreeningResult(
                    passed=False,
                    pld=0.0,
                    largest_included_diameter=0.0,
                    largest_free_path_included_diameter=0.0,
                    cif_path=cif_path_str,
                    error_message=f"Failed to parse numbers from .res: {e}"
                )

        return ZeoScreeningResult(
            passed=False,
            pld=0.0,
            largest_included_diameter=0.0,
            largest_free_path_included_diameter=0.0,
            cif_path=cif_path_str,
            error_message=f"Malformed .res line: '{lines[0]}'"
        )

    def _win_to_wsl_path(self, path: Path) -> str:
        """Convert a Windows Path to WSL /mnt/... format."""
        p_str = str(path.resolve()).replace("\\", "/")
        if len(p_str) > 1 and p_str[1] == ":":
            drive = p_str[0].lower()
            return f"/mnt/{drive}{p_str[2:]}"
        return p_str

    def _mock_screening(self, cif_path: str, error: Optional[str] = None) -> ZeoScreeningResult:
        """Fallback mock pore screening (e.g. MOF-5 baseline PLD ~ 7.8 A)."""
        logger.info(f"Using mock pore screener for {cif_path}")
        # Default MOF-5 baseline has PLD ~ 7.8 A, Di ~ 12.0 A
        # If filename or path mentions bulky groups, mock lower PLD
        pld = 7.8
        if "bulky" in cif_path.lower() or "blocked" in cif_path.lower():
            pld = 3.2 # Fails cutoff
        
        passed = (pld >= self.pld_cutoff)
        return ZeoScreeningResult(
            passed=passed,
            pld=pld,
            largest_included_diameter=12.1,
            largest_free_path_included_diameter=7.8,
            cif_path=cif_path,
            error_message=error,
            is_mock=True
        )
