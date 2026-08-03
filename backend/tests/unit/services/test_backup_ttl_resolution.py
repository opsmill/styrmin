"""Unit tests for backup retention TTL resolution (016 / US1 + US2).

Covers the deepest-wins scope resolution and the built-in fallback in
``styrmin_backend.services.backup.ttl``. This module is the single home of
the pinned ``720h`` literal (SC-004): the Velero builders take the TTL as a
required input, so no other layer asserts a default.
"""

from __future__ import annotations

from typing import get_args

from styrmin_backend.services.backup.ttl import (
    DEFAULT_BACKUP_TTL,
    BackupTtlSource,
    resolve_backup_ttl,
)


def test_default_backup_ttl_is_pinned_to_720h() -> None:
    """The built-in retention is ``720h`` — pinned here and nowhere else.

    SC-004: behaviour is unchanged for operators who never set a policy, so
    the constant is a contract. This is the only assertion on the literal in
    the suite (the builders no longer carry a default).
    """
    assert DEFAULT_BACKUP_TTL == "720h"


def test_environment_scope_wins_over_cluster() -> None:
    """The environment hop beats the shallower cluster hop (FR-001)."""
    ttl, source = resolve_backup_ttl(
        deployment_config=None,
        environment_config={"backup_ttl": "2160h"},
        cluster_config={"backup_ttl": "8760h"},
    )
    assert (ttl, source) == ("2160h", "environment")


def test_environment_scope_applies_when_deployment_unset() -> None:
    """A deployment config without the key is transparent (FR-001)."""
    ttl, source = resolve_backup_ttl(
        deployment_config={"db_size": "10Gi"},
        environment_config={"backup_ttl": "2160h"},
        cluster_config=None,
    )
    assert (ttl, source) == ("2160h", "environment")


def test_deployment_scope_wins_over_environment_and_cluster() -> None:
    """The deepest hop wins outright (016 / US2, FR-001).

    A single critical deployment overrides its environment's policy while
    siblings keep following the environment — the deployment hop must beat
    both shallower scopes even when all three carry a value.
    """
    ttl, source = resolve_backup_ttl(
        deployment_config={"backup_ttl": "8760h"},
        environment_config={"backup_ttl": "2160h"},
        cluster_config={"backup_ttl": "720h"},
    )
    assert (ttl, source) == ("8760h", "deployment")


def test_cluster_scope_applies_when_deployment_and_environment_unset() -> None:
    """The cluster hop is the org-wide baseline (016 / US2, FR-001).

    With neither deployment nor environment setting a policy, the value set
    at cluster-create time applies rather than the built-in default.
    """
    ttl, source = resolve_backup_ttl(
        deployment_config={"db_size": "10Gi"},
        environment_config={"ingress_class": "nginx"},
        cluster_config={"backup_ttl": "4320h"},
    )
    assert (ttl, source) == ("4320h", "cluster")


def test_null_at_deployment_scope_skips_to_the_environment_hop() -> None:
    """An explicit ``backup_ttl: None`` is transparent, not a clear (FR-001).

    Full-replacement clients omit-or-null the field; a stored ``None`` must
    fall through to the next scope rather than resolve to the default and
    shadow the environment policy.
    """
    ttl, source = resolve_backup_ttl(
        deployment_config={"backup_ttl": None},
        environment_config={"backup_ttl": "2160h"},
        cluster_config={"backup_ttl": "720h"},
    )
    assert (ttl, source) == ("2160h", "environment")


def test_null_at_deployment_and_environment_skips_to_the_cluster_hop() -> None:
    """Two consecutive null hops fall through to cluster scope (FR-001)."""
    ttl, source = resolve_backup_ttl(
        deployment_config={"backup_ttl": None},
        environment_config={"backup_ttl": None},
        cluster_config={"backup_ttl": "8760h"},
    )
    assert (ttl, source) == ("8760h", "cluster")


def test_null_at_every_scope_falls_back_to_the_built_in_default() -> None:
    """All three scopes storing ``None`` is indistinguishable from unset."""
    assert resolve_backup_ttl(
        deployment_config={"backup_ttl": None},
        environment_config={"backup_ttl": None},
        cluster_config={"backup_ttl": None},
    ) == ("720h", "default")


def test_all_scopes_unset_falls_back_to_the_built_in_default() -> None:
    """No scope sets a policy → the built-in default with ``"default"`` source.

    FR-003: an operator who never touches the knob keeps today's retention.
    """
    assert resolve_backup_ttl(
        deployment_config=None,
        environment_config=None,
        cluster_config=None,
    ) == ("720h", "default")


def test_empty_config_dicts_fall_back_to_the_built_in_default() -> None:
    """Present-but-empty config dicts contribute nothing (FR-003)."""
    assert resolve_backup_ttl(
        deployment_config={},
        environment_config={},
        cluster_config={},
    ) == ("720h", "default")


def test_source_scope_vocabulary_is_exactly_the_four_scopes() -> None:
    """``BackupTtlSource`` enumerates the three scopes plus ``"default"``.

    The value lands on ``Backup.metadata_["ttl_source"]`` as an audit record,
    so the vocabulary is part of the contract (data-model.md §Backup).
    """
    assert set(get_args(BackupTtlSource)) == {
        "deployment",
        "environment",
        "cluster",
        "default",
    }


def test_every_resolvable_source_is_a_declared_source_scope() -> None:
    """Each hop reports a source drawn from the declared vocabulary."""
    declared = set(get_args(BackupTtlSource))
    observed = {
        resolve_backup_ttl({"backup_ttl": "1h"}, None, None)[1],
        resolve_backup_ttl(None, {"backup_ttl": "1h"}, None)[1],
        resolve_backup_ttl(None, None, {"backup_ttl": "1h"})[1],
        resolve_backup_ttl(None, None, None)[1],
    }
    assert observed == declared
