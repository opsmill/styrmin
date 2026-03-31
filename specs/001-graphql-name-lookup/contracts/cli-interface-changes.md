# CLI Interface Changes for Name-Based Resource Lookup

**Feature**: 001-graphql-name-lookup
**Date**: 2026-03-29

## Cluster Commands

### `styrminctl clusters get <name> [--id UUID]`

**Before**: `styrminctl clusters get <cluster_id>`
**After**: Name is default positional. UUID via `--id` flag.

```bash
# By name (new default)
styrminctl clusters get us-east-1

# By UUID (backward compat via flag)
styrminctl clusters get --id a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### `styrminctl clusters delete <name> [--id UUID]`

**Before**: `styrminctl clusters delete <cluster_id>`
**After**: Same pattern as `get`.

### `styrminctl clusters create <name>` -- unchanged

### `styrminctl clusters list` -- unchanged

## Environment Commands

### `styrminctl environments get <name> [--cluster NAME] [--cluster-id UUID] [--id UUID]`

**Before**: `styrminctl environments get <environment_id>`
**After**: Name is default positional. `--cluster` defaults to "default".

```bash
# By name in default cluster
styrminctl environments get staging

# By name in specific cluster
styrminctl environments get staging --cluster us-east-1

# By UUID (backward compat)
styrminctl environments get --id def-456
```

### `styrminctl environments delete <name> [--cluster NAME] [--cluster-id UUID] [--id UUID]`

**Before**: `styrminctl environments delete <environment_id>`
**After**: Same pattern as `get`.

### `styrminctl environments create <name> [--cluster NAME] [--cluster-id UUID]`

**Before**: `styrminctl environments create <name> <cluster_id>`
**After**: Cluster specified via flags instead of positional. `--cluster` defaults to "default".

```bash
# Create in default cluster
styrminctl environments create staging

# Create in specific cluster
styrminctl environments create staging --cluster us-east-1
```

### `styrminctl environments list` -- unchanged

## Deployment Commands

### `styrminctl deployments create <driver> <version> <environment_name> [--cluster NAME] [--cluster-id UUID] [--id UUID]`

**Before**: `styrminctl deployments create <driver> <version> <environment_id>`
**After**: Environment name as positional, cluster via flags.

```bash
# By environment name
styrminctl deployments create my-driver 1.0 staging --cluster us-east-1

# By environment UUID (backward compat)
styrminctl deployments create my-driver 1.0 --id def-456
```

## Backup Storage Location Commands

### `styrminctl backup-locations assign <environment_name> <bsl_id> [--cluster NAME] [--cluster-id UUID] [--id UUID]`

**Before**: `styrminctl backup-locations assign <environment_id> <bsl_id>`
**After**: Environment name as positional, cluster via flags.

### `styrminctl backup-locations unassign <environment_name> [--cluster NAME] [--cluster-id UUID] [--id UUID]`

**Before**: `styrminctl backup-locations unassign <environment_id>`
**After**: Same pattern.

## Validation Rules (CLI-level)

1. If both positional name and `--id` are provided → error: "Provide either a name or --id, not both"
2. If neither positional name nor `--id` provided → error: "Either a name or --id is required"
3. If both `--cluster` and `--cluster-id` provided → error: "Provide either --cluster or --cluster-id, not both"
4. `--cluster` defaults to "default" when omitted (applies only to environment-related operations)
5. When `--id` is used for environment lookup, `--cluster` and `--cluster-id` are ignored (UUID is sufficient)
