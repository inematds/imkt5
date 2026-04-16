"""Sanidade dos tipos canônicos."""

import pytest

from imkt4.types import (
    Approval,
    ApprovalMode,
    BindingKind,
    Job,
    JobPriority,
    PublishBinding,
    SourceBinding,
)


def test_job_requires_worker_or_capability():
    with pytest.raises(ValueError):
        Job(
            job_id="j1",
            tenant_id="t1",
            user_id="u1",
        )


def test_job_with_capability_ok():
    j = Job(
        job_id="j1",
        tenant_id="t1",
        user_id="u1",
        required_capability="image.generation",
    )
    assert j.required_capability == "image.generation"
    assert j.worker_type is None


def test_job_with_worker_type_ok():
    j = Job(
        job_id="j1",
        tenant_id="t1",
        user_id="u1",
        worker_type="inemaimg",
    )
    assert j.worker_type == "inemaimg"
    assert j.priority == JobPriority.NORMAL


def test_approval_defaults_to_none():
    a = Approval()
    assert a.mode == ApprovalMode.NONE
    assert a.timeout_seconds == 1800


def test_source_and_publish_bindings():
    s = SourceBinding(
        binding_id="s1",
        tenant_id="t1",
        kind=BindingKind.YOUTUBE,
        external_id="UC2QbQDyPKuHk93dwo5iq3Sw",
        credentials_ref="secrets/s1",
    )
    p = PublishBinding(
        binding_id="p1",
        tenant_id="t1",
        kind=BindingKind.YOUTUBE,
        external_id="UCavuQHkxBSAZbzRoOm6Gq4g",
        credentials_ref="secrets/p1",
    )
    assert s.enabled and p.enabled
    assert s.kind == p.kind
