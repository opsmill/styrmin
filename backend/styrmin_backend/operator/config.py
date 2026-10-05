"""Operator constants.

Centralized definitions for labels, annotations and Kubernetes resource names
used by the kopf-based operator. Configurable values live in
``styrmin_backend.config.OperatorSettings``.
"""

# --- Labels ---
LABEL_MANAGED_BY = "app.kubernetes.io/managed-by"
LABEL_MANAGED_BY_VALUE = "styrmin"
LABEL_UTILITY_KIND = "styrmin.io/utility-kind"
LABEL_RELEASE_REFERENCE = "styrmin.io/release-reference"
LABEL_OPERATOR_MANAGED = "styrmin.io/operator-managed"
LABEL_OPERATOR_MANAGED_VALUE = "true"

# --- Annotations ---
ANNOTATION_DEPLOYMENT_IN_PROGRESS = "styrmin.io/deployment-in-progress"
ANNOTATION_DEPLOYMENT_ID = "styrmin.io/deployment-id"

# --- Kubernetes Event reasons ---
EVENT_RECONCILE_SUCCEEDED = "ReconcileSucceeded"
EVENT_DRIFT_DETECTED = "DriftDetected"
EVENT_RECONCILE_FAILED = "ReconcileFailed"

# --- Kubernetes resource constants ---
HELMRELEASE_GROUP = "helm.toolkit.fluxcd.io"
HELMRELEASE_VERSION = "v2"
HELMRELEASE_PLURAL = "helmreleases"

# --- StyrminDeployment CRD constants ---
CRD_GROUP = "styrmin.io"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "styrmindeployments"
CRD_KIND = "StyrminDeployment"

# --- Labels for CRD-managed resources ---
LABEL_DEPLOYMENT_CRD = "styrmin.io/deployment-crd"
LABEL_RESOURCE_PHASE = "styrmin.io/resource-phase"

# --- Resource phase values ---
PHASE_PREREQUISITES = "prerequisites"
PHASE_HELM = "helm"
PHASE_SERVICES = "services"

# --- Backoff ---
BACKOFF_BASE_SECONDS = 5
BACKOFF_MAX_SECONDS = 300
