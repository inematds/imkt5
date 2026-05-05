"""Tipos canônicos do imkt5.

Todo componente (canal, gateway, recipe runner, worker) fala estas
estruturas. Alterar qualquer uma é uma mudança de contrato cross-cutting.
"""

from imkt5.types.approvals import (
    Approval,
    ApprovalDecision,
    ApprovalLog,
    ApprovalMode,
    EscalationPolicy,
)
from imkt5.types.bindings import BindingKind, PublishBinding, SourceBinding
from imkt5.types.capabilities import (
    RegisteredWorker,
    WorkerHealth,
    WorkerStatus,
)
from imkt5.types.jobs import Job, JobPriority, JobResult, JobStatus
from imkt5.types.messages import IncomingMessage, MessageAttachment, OutgoingMessage
from imkt5.types.tenants import ChannelBinding, ChannelKind, Tenant, User

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
