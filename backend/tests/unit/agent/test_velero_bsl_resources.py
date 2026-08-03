"""Tests for VeleroBackupStorageLocation dataclass and VeleroBackup storage_location field."""

from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackup,
    VeleroBackupStorageLocation,
)


def test_velero_backup_without_storage_location():
    """VeleroBackup without storage_location should not include storageLocation in spec."""
    backup = VeleroBackup(
        name="test-backup",
        namespace="styrmin",
        included_namespaces=["styrmin-deployment-1"],
        ttl="720h",
    )
    rendered = backup.render()
    assert "storageLocation" not in rendered["spec"]


def test_velero_backup_with_storage_location():
    """VeleroBackup with storage_location should include storageLocation in spec."""
    backup = VeleroBackup(
        name="test-backup",
        namespace="styrmin",
        included_namespaces=["styrmin-deployment-1"],
        ttl="720h",
        storage_location="styrmin-bsl-my-location",
    )
    rendered = backup.render()
    assert rendered["spec"]["storageLocation"] == "styrmin-bsl-my-location"


def test_velero_bsl_render_bsl():
    """VeleroBackupStorageLocation should render the BSL CRD correctly."""
    bsl = VeleroBackupStorageLocation(
        name="styrmin-bsl-my-bsl",
        namespace="styrmin",
        bucket="my-bucket",
        region="us-east-1",
        endpoint="https://s3.example.com",
        credential_secret_name="styrmin-bsl-my-bsl-credentials",
        bsl_id="550e8400-e29b-41d4-a716-446655440000",
    )
    rendered = bsl.render_bsl()

    assert rendered["apiVersion"] == "velero.io/v1"
    assert rendered["kind"] == "BackupStorageLocation"
    assert rendered["metadata"]["name"] == "styrmin-bsl-my-bsl"
    assert rendered["metadata"]["namespace"] == "styrmin"
    assert rendered["metadata"]["labels"]["styrmin.io/managed"] == "true"
    assert (
        rendered["metadata"]["labels"]["styrmin.io/bsl-id"]
        == "550e8400-e29b-41d4-a716-446655440000"
    )
    assert rendered["spec"]["provider"] == "aws"
    assert rendered["spec"]["objectStorage"]["bucket"] == "my-bucket"
    assert rendered["spec"]["config"]["region"] == "us-east-1"
    assert rendered["spec"]["config"]["s3ForcePathStyle"] == "true"
    assert rendered["spec"]["config"]["s3Url"] == "https://s3.example.com"
    assert rendered["spec"]["credential"]["name"] == "styrmin-bsl-my-bsl-credentials"
    assert rendered["spec"]["credential"]["key"] == "cloud"


def test_velero_bsl_render_secret():
    """VeleroBackupStorageLocation should render the credential Secret correctly."""
    bsl = VeleroBackupStorageLocation(
        name="styrmin-bsl-my-bsl",
        namespace="styrmin",
        bucket="my-bucket",
        region="us-east-1",
        endpoint="https://s3.example.com",
        credential_secret_name="styrmin-bsl-my-bsl-credentials",
        bsl_id="550e8400-e29b-41d4-a716-446655440000",
    )
    rendered = bsl.render_secret(
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )

    assert rendered["apiVersion"] == "v1"
    assert rendered["kind"] == "Secret"
    assert rendered["metadata"]["name"] == "styrmin-bsl-my-bsl-credentials"
    assert rendered["metadata"]["namespace"] == "styrmin"
    assert rendered["metadata"]["labels"]["styrmin.io/managed"] == "true"
    assert rendered["type"] == "Opaque"

    cloud_data = rendered["stringData"]["cloud"]
    assert "aws_access_key_id = AKIAIOSFODNN7EXAMPLE" in cloud_data
    assert (
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" in cloud_data
    )
    assert "[default]" in cloud_data
