"""Tipos canônicos do imkt4.

Todo componente (canal, gateway, recipe runner, worker) fala estas
estruturas. Alterar qualquer uma é uma mudança de contrato cross-cutting.
"""

from imkt4.types.approvals import (
    Approval,
    ApprovalDecision,
    ApprovalLog,
    ApprovalMode,
    EscalationPolicy,
)
from imkt4.types.bindings import BindingKind, PublishBinding, SourceBinding
from imkt4.types.capabilities import (
    RegisteredWorker,
    WorkerHealth,
    WorkerStatus,
)
from imkt4.types.jobs import Job, JobPriority, JobResult, JobStatus
from imkt4.types.messages import IncomingMessage, MessageAttachment, OutgoingMessage
from imkt4.types.tenants import ChannelBinding, ChannelKind, Tenant, User

__all__ = [
    # approvals
    "Approval",
    "ApprovalDecision",
    "ApprovalLog",
    "ApprovalMode",
    "EscalationPolicy",
    # bindings
    "BindingKind",
    "PublishBinding",
    "SourceBinding",
    # capabilities
    "RegisteredWorker",
    "WorkerHealth",
    "WorkerStatus",
    # jobs
    "Job",
    "JobPriority",
    "JobResult",
    "JobStatus",
    # messages
    "IncomingMessage",
    "MessageAttachment",
    "OutgoingMessage",
    # tenants
    "ChannelBinding",
    "ChannelKind",
    "Tenant",
    "User",
]
