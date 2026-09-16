"""Cross-cutting security tests for BIG #5.

Each test pins one architectural rule from the BIG brief. They
are intentionally redundant with the module tests: security
properties deserve their own tripwire file.
"""

import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "coordinator" / "app"


def source_of(*names: str) -> str:
    return "\n".join(
        (APP / name).read_text(encoding="utf-8") for name in names)


def test_no_shell_or_process_execution_in_write_layer():
    source = source_of("controlled_writes.py", "inventory_writes.py",
                       "verification.py", "project_package.py")
    for token in ("subprocess", "os.system", "os.popen", "shell=True",
                  "eval(", "exec(", "__import__"):
        assert token not in source, f"forbidden token: {token}"


def test_no_sql_in_write_layer():
    source = source_of("controlled_writes.py", "inventory_writes.py",
                       "verification.py", "project_package.py",
                       "git_commit.py")
    for token in ("sqlite3", "SELECT ", "INSERT ", "UPDATE ", "DELETE ",
                  "DROP ", "ALTER "):
        assert token not in source, f"forbidden token: {token}"


def test_no_direct_database_writes_from_mycelium():
    """Mycelium never imports INVENTory database code."""
    source = source_of("controlled_writes.py", "inventory_writes.py",
                       "verification.py", "git_commit.py",
                       "project_package.py", "main.py")
    assert "inventory.app" not in source
    # The write path reaches INVENTory exclusively over HTTP.
    assert "httpx" in source_of("inventory_writes.py")


def test_git_module_has_no_push_or_remote_capability():
    source = source_of("git_commit.py")
    for token in ('"push"', "'push'", "clone", "remote",
                  "getpass", "keyring",
                  "shell=True", "os.system", "eval(",
                  "Authorization", "credential.helper"):
        assert token not in source, f"forbidden token: {token}"


def test_ai_cannot_set_human_verified_anywhere():
    from coordinator.app.controlled_writes import propose_write
    from coordinator.app.inventory_read import Provenance
    from coordinator.app.inventory_writes import propose_inventory_write
    ai_claim = Provenance(source_type="ai-generated",
                          creator_id="model",
                          human_verified=True)
    with pytest.raises(ValueError):
        propose_write("wrt-s1", "inventory.create", "t", {},
                      actor="m", provenance=ai_claim)
    with pytest.raises(Exception):
        propose_inventory_write(
            "wrt-s2", "create", "object", {"name": "x"}, actor="m",
            provenance=ai_claim)


def test_approval_never_marks_verified():
    from coordinator.app.controlled_writes import (
        decide_write,
        propose_write,
        request_write_approval,
    )
    from coordinator.app.inventory_read import Provenance
    proposal = propose_write(
        "wrt-s3", "inventory.create", "t", {}, actor="m",
        provenance=Provenance(source_type="ai-generated",
                              creator_id="m",
                              human_verified=False))
    approval = decide_write(request_write_approval(proposal),
                            proposal, "YES")
    assert approval.approved is True
    assert proposal.provenance.human_verified is False


def test_missing_or_failed_verification_is_never_success():
    from coordinator.app.verification import (
        VerificationResult,
        is_verified,
    )
    assert is_verified(None) is False
    for outcome in ("failed", "inconclusive"):
        result = VerificationResult(
            verification_id="ver_s", proposal_id="wrt_s",
            result_fingerprint="0" * 64, outcome=outcome,
            method="inventory.readback")
        assert is_verified(result) is False


def test_stale_approval_cannot_authorize_execution():
    from coordinator.app.controlled_writes import (
        decide_write,
        propose_write,
        request_write_approval,
        revalidate,
    )
    from coordinator.app.inventory_read import Provenance
    proposal = propose_write(
        "wrt-s4", "inventory.create", "t", {}, actor="m",
        provenance=Provenance(source_type="ai-generated",
                              creator_id="m",
                              human_verified=False),
        ttl_seconds=1)
    approval = decide_write(request_write_approval(proposal),
                            proposal, "YES")
    with pytest.raises(ValueError, match="stale"):
        revalidate(proposal, approval,
                   now_str="2999-01-01T00:00:00+00:00")


def test_fingerprint_mismatch_cannot_authorize_execution():
    from coordinator.app.controlled_writes import (
        decide_write,
        propose_write,
        request_write_approval,
        revalidate,
    )
    from coordinator.app.inventory_read import Provenance
    proposal = propose_write(
        "wrt-s5", "inventory.create", "t", {"a": 1}, actor="m",
        provenance=Provenance(source_type="ai-generated",
                              creator_id="m",
                              human_verified=False))
    approval = decide_write(request_write_approval(proposal),
                            proposal, "YES")
    tampered = proposal.model_copy(update={"payload": {"a": 2}})
    with pytest.raises(ValueError, match="does not bind"):
        revalidate(tampered, approval)


def test_no_credential_handling_in_new_modules():
    source = source_of("controlled_writes.py", "inventory_writes.py",
                       "verification.py", "git_commit.py",
                       "project_package.py")
    for token in ("Authorization", "Bearer ", "getpass", "keyring",
                  "client_secret", "private_key"):
        assert token not in source, f"forbidden token: {token}"


def test_project_package_drops_secret_like_keys(tmp_path):
    from coordinator.app.project_context import ProjectContext
    from coordinator.app.project_package import build_project_package
    from coordinator.app.inventory_read import Provenance
    project = ProjectContext(
        project_id="prj-s", name="s", repository=str(tmp_path),
        working_directory=str(tmp_path),
        provenance=Provenance(source_type="user-created",
                              creator_id="human",
                              human_verified=True))
    package = build_project_package(
        project,
        entities=[{"entity_type": "object", "entity_id": "obj_1",
                   "title": "t", "snippet": "s",
                   "api_token": "LEK",
                   "provenance": {"source_type": "user-created",
                                  "human_verified": True}}])
    assert "LEK" not in str(package)
