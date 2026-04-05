# Contract: StyrminDeployment CRD Schema

**Branch**: `001-deployment-crd` | **Date**: 2026-04-05

## CRD Definition

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: styrmindeployments.styrmin.io
spec:
  group: styrmin.io
  scope: Namespaced
  names:
    kind: StyrminDeployment
    plural: styrmindeployments
    singular: styrmindeployment
    shortNames:
      - sd
  versions:
    - name: v1alpha1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                deploymentId:
                  type: string
                  description: UUID linking to Styrmin database deployment
                releaseReference:
                  type: string
                  description: Kubernetes release reference
                appName:
                  type: string
                  description: Application name from the driver
                appVersion:
                  type: string
                  description: Application version being deployed
                context:
                  type: object
                  x-kubernetes-preserve-unknown-fields: true
                  description: Serialized GlobalContext
                helm:
                  type: object
                  properties:
                    chart:
                      type: object
                      x-kubernetes-preserve-unknown-fields: true
                    repository:
                      type: object
                      x-kubernetes-preserve-unknown-fields: true
                labels:
                  type: object
                  x-kubernetes-preserve-unknown-fields: true
                parameters:
                  type: object
                  x-kubernetes-preserve-unknown-fields: true
              required:
                - deploymentId
                - releaseReference
                - appName
                - appVersion
                - context
                - helm
            status:
              type: object
              x-kubernetes-preserve-unknown-fields: true
              properties:
                phase:
                  type: string
                  enum:
                    - Pending
                    - CreatingPrerequisites
                    - CreatingHelmRelease
                    - CreatingServices
                    - Ready
                    - Failed
                    - Deleting
                message:
                  type: string
                conditions:
                  type: array
                  items:
                    type: object
                    properties:
                      type:
                        type: string
                      status:
                        type: string
                        enum: ["True", "False", "Unknown"]
                      reason:
                        type: string
                      message:
                        type: string
                      lastTransitionTime:
                        type: string
                        format: date-time
                managedResources:
                  type: object
                  properties:
                    networkPolicies:
                      type: integer
                    secrets:
                      type: integer
                    helmReleases:
                      type: integer
                    services:
                      type: integer
                    middlewares:
                      type: integer
      subresources:
        status: {}
      additionalPrinterColumns:
        - name: Phase
          type: string
          jsonPath: .status.phase
        - name: App
          type: string
          jsonPath: .spec.appName
        - name: Version
          type: string
          jsonPath: .spec.appVersion
        - name: Age
          type: date
          jsonPath: .metadata.creationTimestamp
```

## Example Resource

```yaml
apiVersion: styrmin.io/v1alpha1
kind: StyrminDeployment
metadata:
  name: infrahub-prod
  namespace: deploy-abc123
  labels:
    app.kubernetes.io/managed-by: styrmin
spec:
  deploymentId: "550e8400-e29b-41d4-a716-446655440000"
  releaseReference: "abc123def"
  appName: "infrahub"
  appVersion: "1.7.2"
  context:
    cluster:
      config:
        storage_class: "standard"
        ingress_class: "traefik"
    environment:
      config: {}
      name: "production"
    deployment:
      config: {}
    instance:
      config: {}
      deployment_id: "550e8400-e29b-41d4-a716-446655440000"
      namespace: "deploy-abc123"
      release_reference: "abc123def"
    app:
      name: "infrahub"
      version: "1.7.2"
    utilities:
      - kind: "ingress"
      - kind: "service-discovery"
    labels:
      environment_id: "env-uuid"
    parameters: {}
    services: {}
    deployed_services: []
  helm:
    chart:
      id: "chart-uuid"
      name: "infrahub"
      version: "4.16.3"
      values_template: "..."
    repository:
      id: "repo-uuid"
      url: "oci://registry.opsmill.io/opsmill/chart/infrahub"
  labels:
    environment_id: "env-uuid"
  parameters: {}
status:
  phase: Ready
  message: "All resources deployed successfully"
  conditions:
    - type: NetworkPoliciesReady
      status: "True"
      reason: AllApplied
      message: "5 NetworkPolicies created"
      lastTransitionTime: "2026-04-05T10:30:00Z"
    - type: SecretsReady
      status: "True"
      reason: AllApplied
      message: "2 Secrets created"
      lastTransitionTime: "2026-04-05T10:30:01Z"
    - type: HelmReleaseReady
      status: "True"
      reason: FluxReady
      message: "HelmRelease abc123def is Ready"
      lastTransitionTime: "2026-04-05T10:31:15Z"
    - type: ServicesReady
      status: "True"
      reason: AllApplied
      message: "3 Services created"
      lastTransitionTime: "2026-04-05T10:31:16Z"
    - type: MiddlewaresReady
      status: "True"
      reason: AllApplied
      message: "1 Middleware created"
      lastTransitionTime: "2026-04-05T10:31:16Z"
    - type: Ready
      status: "True"
      reason: AllPhasesComplete
      message: "Deployment is healthy"
      lastTransitionTime: "2026-04-05T10:31:16Z"
  managedResources:
    networkPolicies: 5
    secrets: 2
    helmReleases: 1
    services: 3
    middlewares: 1
```

## Prefect Flow Contract

The Prefect flow creates the CRD with a single `upsert_custom_resource` call:

**Create**: `POST /apis/styrmin.io/v1alpha1/namespaces/{ns}/styrmindeployments`  
**Update**: `PATCH /apis/styrmin.io/v1alpha1/namespaces/{ns}/styrmindeployments/{name}`  
**Delete**: `DELETE /apis/styrmin.io/v1alpha1/namespaces/{ns}/styrmindeployments/{name}`

The Prefect flow does NOT:
- Create HelmReleases
- Create NetworkPolicies, Secrets, Services, or Middlewares
- Poll HelmRelease status
- Manage namespace labels for utility resources
