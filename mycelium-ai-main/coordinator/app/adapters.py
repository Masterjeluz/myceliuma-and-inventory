"""Adapter interface and deterministic reference adapter (M6.1).

The Adapter protocol ends at PROPOSAL. This module offers data validation
and proposal construction only; it performs no side effects of any kind.

ReferenceNoopAdapter is mock-only and fully deterministic: given the same
request it always returns the same proposal. It performs no analysis; it
structures the input into an explicit proposal that a human must approve.
"""

from abc import ABC, abstractmethod

from .adapter_contracts import AdapterProposal, AdapterRequest
from .inventory_read import Provenance

REFERENCE_ADAPTER_ID = "reference-noop"


class Adapter(ABC):
    """Executionless adapter interface: validate in, proposal out."""

    adapter_id: str = ""

    @abstractmethod
    def propose(self, request: AdapterRequest) -> AdapterProposal:
        """Produce an AdapterProposal for a validated request. No side effects."""
        raise NotImplementedError


class ReferenceNoopAdapter(Adapter):
    """Deterministic mock adapter. Proposes only; never acts."""

    adapter_id = REFERENCE_ADAPTER_ID

    def propose(self, request: AdapterRequest) -> AdapterProposal:
        if request.adapter_id != self.adapter_id:
            raise ValueError(
                f"Request targets adapter '{request.adapter_id}', "
                f"this is '{self.adapter_id}'"
            )
        input_keys = sorted(str(key) for key in request.input.keys())
        discussed = ", ".join(input_keys) if input_keys else "no input fields"
        source = request.provenance
        proposal_id = f"prop-{request.request_id}"[:80]
        return AdapterProposal(
            proposal_id=proposal_id,
            request_id=request.request_id,
            adapter_id=self.adapter_id,
            model_id=request.model_id,
            node_id=request.node_id,
            task_id=request.task_id,
            proposed_action=(
                "No action taken. A human must review the input "
                f"({discussed}) and decide the next step."
            ),
            expected_output="A human-approved plan, or a rejection with a reason.",
            risks=["input has not been independently verified",
                   "no execution has been performed"],
            provenance=Provenance(
                source_type="ai-generated",
                creator_id=f"adapter:{self.adapter_id}",
                human_verified=False,
                notes=(f"proposal for request {request.request_id}; "
                       f"input provenance {source.source_type}/"
                       f"{source.creator_id} preserved without endorsement"),
            ),
            requires_approval=True,
        )
