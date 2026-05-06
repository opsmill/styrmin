"""Environment variable resolution, validation, and post-render injection.

Free-form ``dict[str, str]`` env vars settable at three scopes (environment,
deployment, per-component) with per-key deepest-wins precedence, auto-injected
into rendered workloads via the existing post-render injection pipeline.

Modules:

* :mod:`validator` — name regex, size caps (per-value, per-scope, resolved),
  duplicate-name rejection, risky-name soft-warning.
* :mod:`resolver` — env→dep→comp deepest-wins merge plus orphan detection.
* :mod:`patch_builder` — JSON-patch builder for ``container[0].env`` (mirrors
  :class:`~styrmin_backend.agent.service.kubernetes.resources.blocks.patches.ResourcesPatch`).
* :mod:`exceptions` — :class:`~styrmin_backend.services.exceptions.ServiceError`
  subclasses surfaced through ``StructuredErrorExtension`` as precise
  GraphQL ``extensions.code`` values.

See ``specs/008-deployment-env-vars/`` for the full feature spec, plan, and
ADR-019 for the durable design decisions.
"""
