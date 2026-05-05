"""Gates de aprovação — três modos.

Cada gate implementa `ApprovalGate` (definido em `runner.py`) e resolve
a decisão *assíncronamente*, chamando de volta `runner.on_approval_decided`
quando a resposta chegar.
"""

from imkt5.recipes.approvals.dispatcher import CompositeApprovalGate

__all__ = ["CompositeApprovalGate"]
