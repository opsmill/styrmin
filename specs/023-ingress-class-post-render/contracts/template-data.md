# Contract: `ingress_class` in the Values Template Data

**Feature**: [../spec.md](../spec.md) | **Research**: [../research.md](../research.md) (D-004)

The contract between `ApplicationHelmReleaseBuilder.render_value_template` and a driver's `values.j2.yml`.

## Before this change

| Mode | `{{ instance.config.ingress_class }}` (and the `cluster`, `environment`, `deployment` sections) |
|------|---------------------------------------------------------------------------------------------------|
| Dedicated ingress controller on | absent; renders as an empty string |
| Dedicated ingress controller off | the resolved value |

## After this change

| Mode | `{{ instance.config.ingress_class }}` (and the `cluster`, `environment`, `deployment` sections) |
|------|---------------------------------------------------------------------------------------------------|
| Dedicated ingress controller on | the resolved value |
| Dedicated ingress controller off | the resolved value |

A key is absent only when its value is `None`, through `model_dump(exclude_none=True)`, as for every other config key.

## What a driver author writes

- No Ingress class value in `values.j2.yml`. Styrmin sets or removes the class after the chart renders ([post-render-patch.md](post-render-patch.md)).
- A driver version whose template still sets `className: "{{ instance.config.ingress_class }}"` keeps working in both modes: the class it renders is overwritten in shared mode and removed in dedicated mode.
- A template may read `ingress_class` for other purposes; it now gets the resolved value in dedicated mode instead of an empty value.

## Unchanged

- The driver format (`driver.styrmin.yml`), the `ingress_class` config key, the GraphQL schema, the SDK, `styrminctl` and the frontend.
