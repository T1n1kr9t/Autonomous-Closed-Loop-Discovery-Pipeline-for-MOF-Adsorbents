"""Smoke tests for Senior Project Pipeline components."""

import pytest
from pathlib import Path

from src.chemistry.rdkit_validator import RDKitValidator
from src.screening.zeo_screener import ZeoScreener
from src.simulation.raspa_generator import RASPAGenerator
from src.simulation.raspa_parser import RASPADataParser
from src.chemistry.pormake_builder import PORMAKEBuilder
from src.agents.prompts import DesignTarget
from src.agents.chemist_agents import ChemistAgent
from src.agents.orchestrator import PipelineOrchestrator


def test_rdkit_validator():
    validator = RDKitValidator()
    # Test valid BDC-NH2
    res_valid = validator.validate_smiles("O=C(O)c1cc(N)ccc1C(=O)O")
    assert res_valid.is_valid is True
    assert res_valid.molecular_weight > 150.0

    # Test invalid SMILES
    res_invalid = validator.validate_smiles("Invalid_Non_Smiles_String")
    assert res_invalid.is_valid is False

    # Test single-carboxylic acid (insufficient anchors for MOF)
    res_single = validator.validate_smiles("CC(=O)O")
    assert res_single.is_valid is False


def test_zeo_screener_mock():
    screener = ZeoScreener(pld_cutoff=3.8)
    # Test normal mock
    res = screener.screen_cif("dummy_mof.cif", force_mock=True)
    assert res.passed is True
    assert res.pld >= 3.8

    # Test bulky mock
    res_bulky = screener.screen_cif("dummy_bulky_blocked.cif", force_mock=True)
    assert res_bulky.passed is False
    assert res_bulky.pld < 3.8


def test_raspa_generator():
    generator = RASPAGenerator(default_cycles=1500, temperature=298.15)
    content = generator.generate_input(framework_name="MOF-5_test")
    assert "SimulationType" in content
    assert "NumberOfCycles" in content
    assert "1500" in content
    assert "Dubbeldam2007FlexibleIRMOF-1" in content
    assert "MOF-5_test" in content


def test_pormake_builder_template():
    builder = PORMAKEBuilder(output_dir="data/generated_cifs")
    res = builder.build_mof("O=C(O)c1cc(N)ccc1C(=O)O", material_name="test_mof5_nh2", force_mock=True)
    assert res.success is True
    assert Path(res.cif_path).exists()
    assert Path(res.cif_path).stat().st_size > 0


def test_chemist_agent_offline():
    agent = ChemistAgent(provider="offline")
    target = DesignTarget()
    proposal = agent.propose_modification(target, allowed_groups=[], failures=[])
    assert proposal.candidate_name is not None
    assert "O=C" in proposal.modified_linker_smiles or "c1" in proposal.modified_linker_smiles


def test_orchestrator_single_cycle():
    orchestrator = PipelineOrchestrator(use_wsl=True)
    res = orchestrator.run_cycle(candidate_index=99)
    assert res.get("status") in ["success", "failed"]


def test_candidate_indexing_no_overwrite():
    orchestrator = PipelineOrchestrator(use_wsl=True)
    # Check that candidate index for MOF-5-NH2 increments past existing files
    idx = orchestrator._get_next_index_for_candidate("MOF-5-NH2")
    assert idx > 1
    # Check that target CIF file with this index does not exist yet
    cif_file = orchestrator.pormake_builder.output_dir / f"MOF-5-NH2_{idx}.cif"
    assert not cif_file.exists()
