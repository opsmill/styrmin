"""Unit tests for scheduling post-renderer patch assembly (T035, T046, T048).

Focuses on:

* ``AffinityPatch`` rendering the correct strategic-merge YAML shape scoped
  to ``spec.template.spec.affinity.podAffinity`` / ``podAntiAffinity`` only.
* ``build_affinity_patches`` emitting one ``TargetPatch`` per
  pod-template-bearing kind (Deployment, StatefulSet, DaemonSet, Job,
  CronJob, ReplicaSet).
* CronJob path variant (``spec.jobTemplate.spec.template.spec.affinity``).
* ``inject.pod_affinity = False`` producing zero patches.
"""

from __future__ import annotations

import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    AffinityPatch,
    ResourcesPatch,
    RuntimeClassPatch,
)
from styrmin_backend.context.models.config import (
    AffinityBlock,
    AffinityTerm,
    LabelSelector,
    LabelSelectorRequirement,
    PostRenderInjection,
    ResourceRequirements,
    ResourceSpec,
    SchedulingConfig,
    WeightedAffinityTerm,
)
from styrmin_backend.services.scheduling.patch_builder import (
    POD_TEMPLATE_BEARING_KINDS,
    build_affinity_patches,
)


def _term(app: str, topology: str = "kubernetes.io/hostname") -> AffinityTerm:
    return AffinityTerm(
        topology_key=topology,
        label_selector=LabelSelector(match_labels={"app": app}),
    )


class TestAffinityPatchRendering:
    def test_renders_required_under_required_during_scheduling(self) -> None:
        patch = AffinityPatch(
            pod_affinity=AffinityBlock(required=[_term("web")]),
        )
        doc = yaml.safe_load(patch.render_value())

        assert doc["apiVersion"] == "apps/v1"
        assert doc["kind"] == "Deployment"
        pod_affinity = doc["spec"]["template"]["spec"]["affinity"]["podAffinity"]
        required = pod_affinity["requiredDuringSchedulingIgnoredDuringExecution"]
        assert len(required) == 1
        assert required[0]["topologyKey"] == "kubernetes.io/hostname"
        assert required[0]["labelSelector"]["matchLabels"] == {"app": "web"}

    def test_renders_preferred_with_weight_and_pod_affinity_term(self) -> None:
        patch = AffinityPatch(
            pod_affinity=AffinityBlock(
                preferred=[WeightedAffinityTerm(weight=42, term=_term("web"))]
            ),
        )
        doc = yaml.safe_load(patch.render_value())

        preferred = doc["spec"]["template"]["spec"]["affinity"]["podAffinity"][
            "preferredDuringSchedulingIgnoredDuringExecution"
        ]
        assert len(preferred) == 1
        assert preferred[0]["weight"] == 42
        assert preferred[0]["podAffinityTerm"]["topologyKey"] == (
            "kubernetes.io/hostname"
        )

    def test_anti_affinity_rendered_under_pod_anti_affinity(self) -> None:
        patch = AffinityPatch(
            pod_anti_affinity=AffinityBlock(required=[_term("db")]),
        )
        doc = yaml.safe_load(patch.render_value())

        pod_spec = doc["spec"]["template"]["spec"]
        assert "podAntiAffinity" in pod_spec["affinity"]
        assert "podAffinity" not in pod_spec["affinity"]

    def test_does_not_emit_whole_affinity_block(self) -> None:
        """US3's NodeAffinityPatch must compose — so this patch body must
        only include podAffinity/podAntiAffinity keys under affinity, not
        nodeAffinity (which would clobber US3's output).
        """
        patch = AffinityPatch(
            pod_affinity=AffinityBlock(required=[_term("web")]),
        )
        doc = yaml.safe_load(patch.render_value())

        affinity = doc["spec"]["template"]["spec"]["affinity"]
        assert set(affinity.keys()) <= {"podAffinity", "podAntiAffinity"}
        assert "nodeAffinity" not in affinity

    def test_match_expressions_rendered_as_camelCase(self) -> None:
        term = AffinityTerm(
            topology_key="kubernetes.io/hostname",
            label_selector=LabelSelector(
                match_expressions=[
                    LabelSelectorRequirement(
                        key="styrmin/component", operator="In", values=["a"]
                    )
                ]
            ),
        )
        patch = AffinityPatch(pod_affinity=AffinityBlock(required=[term]))
        doc = yaml.safe_load(patch.render_value())

        req = doc["spec"]["template"]["spec"]["affinity"]["podAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ][0]
        assert "matchExpressions" in req["labelSelector"]
        assert "match_expressions" not in req["labelSelector"]
        assert req["labelSelector"]["matchExpressions"][0]["key"] == (
            "styrmin/component"
        )

    def test_cronjob_variant_uses_jobtemplate_path(self) -> None:
        patch = AffinityPatch(
            pod_affinity=AffinityBlock(required=[_term("web")]),
            api_version="batch/v1",
            kind="CronJob",
        )
        doc = yaml.safe_load(patch.render_value())

        assert doc["kind"] == "CronJob"
        assert "jobTemplate" in doc["spec"]
        assert doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["affinity"][
            "podAffinity"
        ]

    def test_deployment_ref_excluded_from_rendered_output(self) -> None:
        """deployment_ref is expanded by the validator before reaching the
        patch builder. Even if one slipped through, render_value() must NOT
        leak it into the Kubernetes YAML.
        """
        from styrmin_backend.context.models.config import DeploymentReference

        block = AffinityBlock.model_validate(
            {
                "required": [
                    {
                        "topology_key": "kubernetes.io/hostname",
                        "label_selector": {"match_labels": {"a": "b"}},
                    }
                ]
            }
        )
        # Pydantic rejects a term with both label_selector AND deployment_ref
        # set at construction, so mutate post-hoc to simulate a stray value.
        object.__setattr__(
            block.required[0],
            "deployment_ref",
            DeploymentReference(deployment_name="api"),
        )

        patch = AffinityPatch(pod_affinity=block)
        rendered = patch.render_value()
        assert "deploymentRef" not in rendered
        assert "deployment_ref" not in rendered


class TestBuildAffinityPatches:
    def test_emits_one_patch_per_pod_template_bearing_kind(self) -> None:
        resolved = SchedulingConfig(pod_affinity=AffinityBlock(required=[_term("web")]))

        patches = build_affinity_patches(resolved)

        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)
        kinds = {tp.target.kind for tp in patches}
        assert kinds == set(POD_TEMPLATE_BEARING_KINDS)

    def test_no_affinity_emits_no_patches(self) -> None:
        resolved = SchedulingConfig()
        assert build_affinity_patches(resolved) == []

    def test_inject_false_suppresses_patches(self) -> None:
        resolved = SchedulingConfig(pod_affinity=AffinityBlock(required=[_term("web")]))
        inject = PostRenderInjection(pod_affinity=False)

        assert build_affinity_patches(resolved, inject=inject) == []

    def test_inject_default_true_emits_patches(self) -> None:
        resolved = SchedulingConfig(pod_affinity=AffinityBlock(required=[_term("web")]))
        inject = PostRenderInjection()  # all defaults True

        patches = build_affinity_patches(resolved, inject=inject)
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)

    def test_label_selector_narrows_target(self) -> None:
        resolved = SchedulingConfig(pod_affinity=AffinityBlock(required=[_term("web")]))

        patches = build_affinity_patches(
            resolved, label_selector="infrahub/service=server"
        )

        for tp in patches:
            assert tp.target.label_selector == "infrahub/service=server"

    def test_cronjob_patch_uses_batch_v1_and_cronjob_path(self) -> None:
        resolved = SchedulingConfig(pod_affinity=AffinityBlock(required=[_term("web")]))

        patches = build_affinity_patches(resolved)
        cron_patches = [tp for tp in patches if tp.target.kind == "CronJob"]
        assert len(cron_patches) == 1
        rendered = cron_patches[0].patch.render_value()  # type: ignore[attr-defined]
        assert "jobTemplate" in rendered


class TestResourcesPatchRendering:
    """US2: ResourcesPatch emits a JSON-patch document targeting the
    pod-template's container at ``container_index`` (default 0).
    """

    def test_requests_and_limits_rendered(self) -> None:
        patch = ResourcesPatch(
            resources=ResourceRequirements(
                requests=ResourceSpec(cpu="100m", memory="256Mi"),
                limits=ResourceSpec(
                    cpu="1", memory="2Gi", extended={"nvidia.com/gpu": "1"}
                ),
            )
        )
        ops = yaml.safe_load(patch.render_value())

        assert isinstance(ops, list) and len(ops) == 1
        op = ops[0]
        assert op["op"] == "replace"
        assert op["path"] == "/spec/template/spec/containers/0/resources"
        assert op["value"]["requests"] == {"cpu": "100m", "memory": "256Mi"}
        assert op["value"]["limits"] == {
            "cpu": "1",
            "memory": "2Gi",
            "nvidia.com/gpu": "1",
        }

    def test_ephemeral_storage_uses_k8s_hyphenated_key(self) -> None:
        patch = ResourcesPatch(
            resources=ResourceRequirements(
                requests=ResourceSpec(ephemeral_storage="1Gi")
            )
        )
        ops = yaml.safe_load(patch.render_value())
        requests = ops[0]["value"]["requests"]
        assert "ephemeral-storage" in requests
        assert "ephemeral_storage" not in requests

    def test_cronjob_variant_uses_jobtemplate_path(self) -> None:
        patch = ResourcesPatch(
            resources=ResourceRequirements(requests=ResourceSpec(cpu="100m")),
            api_version="batch/v1",
            kind="CronJob",
        )
        ops = yaml.safe_load(patch.render_value())
        assert ops[0]["path"] == (
            "/spec/jobTemplate/spec/template/spec/containers/0/resources"
        )


class TestRuntimeClassPatchRendering:
    """T091: ``RuntimeClassPatch`` emits a strategic-merge patch that
    sets ``spec.template.spec.runtimeClassName`` to the configured value.
    """

    def test_runtime_class_set_on_pod_template(self) -> None:
        patch = RuntimeClassPatch(runtime_class_name="kata")
        doc = yaml.safe_load(patch.render_value())
        assert doc["spec"]["template"]["spec"]["runtimeClassName"] == "kata"

    def test_cronjob_variant_nests_under_jobtemplate(self) -> None:
        patch = RuntimeClassPatch(
            runtime_class_name="kata", api_version="batch/v1", kind="CronJob"
        )
        doc = yaml.safe_load(patch.render_value())
        assert (
            doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["runtimeClassName"]
            == "kata"
        )


class TestPostRendererOrdering:
    """T048: scheduling post-renderer patches must appear AFTER any
    template-derived patches in the HelmRelease ``postRenderers`` pipeline
    so Kustomize applies them last (FR-015 last-writer-wins).
    """

    def test_scheduling_patches_come_after_backup_annotations_in_build(self) -> None:
        import inspect

        from styrmin_backend.agent.service.kubernetes.resources.builders import (
            application,
        )

        build_source = inspect.getsource(
            application.ApplicationHelmReleaseBuilder.build
        )
        # The scheduling helper must be referenced AFTER backup annotations
        # so its patches win over driver-template-derived patches.
        backup_idx = build_source.find("build_backup_annotation_patches")
        scheduling_idx = build_source.find("build_scheduling_post_rendering_patches")
        assert backup_idx != -1, "backup helper reference missing from build()"
        assert scheduling_idx != -1, "scheduling helper not wired into build()"
        assert scheduling_idx > backup_idx, (
            "scheduling patches must be appended after backup annotation "
            "patches so post-render last-writer-wins (FR-015)"
        )
