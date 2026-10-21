"""Values that the Infrahub Helm charts preset, shared by the E2E tests and the demos."""

# The admin token that the upstream Infrahub Helm chart sets in its values
# (`infrahubServer.admin.INFRAHUB_API_TOKEN`) and preseeds as
# `INFRAHUB_INITIAL_ADMIN_TOKEN`, so a new Infrahub accepts it as soon as its
# initial setup completes. Charts 4.33.2 (`infrahub` driver) and 4.19.2
# (`infrahub-enterprise` driver) set the same value. Infrahub 1.6 and later
# require authentication for writes through the SDK. Never print it.
INFRAHUB_ADMIN_TOKEN = "06438eb2-8019-4776-878c-0941b1f1d1ec"  # noqa: S105
