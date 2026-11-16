from deepdiff import DeepDiff
from loguru import logger

from styrmin_backend.domain.models import Instance
from styrmin_backend.services.reconciliation.diffs.diffs import (
    DiffReport,
    InstanceCreation,
    InstanceDeletion,
    InstanceUpdate,
)
from styrmin_backend.services.reconciliation.diffs.serializer import DiffSerializer


def _raw_diff_paths(raw_diffs: dict) -> list[str]:
    """The paths that a DeepDiff ``to_dict()`` names, without their values."""
    paths: list[str] = []
    for changes in raw_diffs.values():
        paths.extend(str(path) for path in changes)
    return sorted(paths)


class Comparator:
    def __init__(
        self, current_instance: Instance | None, new_instance: Instance | None
    ):
        self.current_instance = current_instance
        self.new_instance = new_instance

    def _serialize_value_change_diff(self, raw_diffs: dict) -> InstanceUpdate:
        """Serialize the raw diffs into a more readable format."""
        assert self.new_instance is not None

        serializer = DiffSerializer()

        return InstanceUpdate(
            instance=self.new_instance, diffs=serializer.serialize(raw_diffs=raw_diffs)
        )

    def compare(self) -> DiffReport:
        """Compare the current instance with the new instance."""

        # Handle cases where one of the instances is None
        if self.current_instance is None and self.new_instance is None:
            logger.debug("Both instances are None, no diff to report.")
            return DiffReport(
                diff=None,
                raw=None,
            )

        if self.current_instance is None:
            logger.debug("Current instance is None, new instance is created.")
            return DiffReport(
                diff=InstanceCreation(instance=self.new_instance),  # type: ignore[arg-type]
                raw=None,
            )

        if self.new_instance is None:
            logger.debug("New instance is None, current instance is deleted.")
            return DiffReport(
                diff=InstanceDeletion(instance=self.current_instance), raw=None
            )

        # If both instances are present, compare their attributes
        raw_diffs = DeepDiff(
            t1=self.current_instance.model_dump(),
            t2=self.new_instance.model_dump(),
            ignore_order=True,
            exclude_paths={
                "root['id']",
                "root['name']",
                "root['status']",
                "root['sequence']",
            },
        ).to_dict()

        # No differences found between instances
        if not raw_diffs:
            logger.debug("No differences found between instances.")
            return DiffReport(diff=None, raw=None)

        # Add a process step to collapse context changes
        context_key = r"root['context']"
        if any(
            key.startswith(context_key) for key in raw_diffs.get("values_changed", {})
        ):
            raw_diffs["values_changed"] = {
                path: value
                for path, value in raw_diffs["values_changed"].items()
                if not path.startswith(context_key)
            }
            # Add the context change as a separate entry
            raw_diffs["values_changed"][context_key] = {
                "old_value": self.current_instance.context.model_dump(mode="json"),
                "new_value": self.new_instance.context.model_dump(mode="json"),
            }

        report = DiffReport(
            diff=self._serialize_value_change_diff(raw_diffs), raw=raw_diffs
        )

        # Safety net: if raw diffs exist but the serializer produced no actionable
        # diff entries (e.g. changes only in unhandled DeepDiff categories), treat
        # as no-op rather than generating an InstanceUpdate with empty diffs.
        if isinstance(report.diff, InstanceUpdate) and not report.diff.diffs:
            # The paths only: the raw diffs hold the old and new values (#573).
            logger.warning(
                "Raw diffs detected but no actionable diff entries produced. "
                "Changed paths: {}",
                _raw_diff_paths(raw_diffs),
            )
            return DiffReport(diff=None, raw=raw_diffs)

        logger.debug(f"Diff report: {type(report.diff)}")

        return report
