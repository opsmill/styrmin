"""Environment variable resolution and validation.

Free-form ``dict[str, str]`` env vars settable at three scopes (environment,
deployment, per-component) with per-key deepest-wins precedence. Operator-set
env vars are exposed to driver values templates via
``instance.config.env_vars`` and ``components[<name>].env_vars.config`` —
drivers consume them as the chart requires (010-driver-env-var-consumption).

Modules:

* :mod:`validator` — name regex, size caps (per-value, per-scope, resolved),
  duplicate-name rejection, risky-name soft-warning.
* :mod:`resolver` — env→dep→comp deepest-wins merge plus orphan detection.
* :mod:`exceptions` — :class:`~styrmin_backend.services.exceptions.ServiceError`
  subclasses surfaced through ``StructuredErrorExtension`` as precise
  GraphQL ``extensions.code`` values.

See ``specs/008-deployment-env-vars/`` for the original feature spec and
``specs/010-driver-env-var-consumption/`` for the driver-side consumption
pivot that removed the post-render injection layer.
"""
