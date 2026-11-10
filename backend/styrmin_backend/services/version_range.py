"""The one check that decides whether a version fits a supported-versions range."""

from packaging.specifiers import SpecifierSet
from packaging.version import Version


def version_fits_range(version: Version, supported_versions: str) -> bool:
    """Return whether ``version`` fits the range ``supported_versions``.

    A version fits when the range contains it with prereleases allowed. A
    prerelease therefore fits when its numbers fit, whether or not the range
    names a prerelease: ``1.12.0b0`` fits ``>=1.5,<2.0``. The ordering rules of
    PEP 440 still apply, so ``1.12.0b0`` does not fit ``>=1.12.0`` (it is below
    the lower bound) and ``2.0.0b1`` does not fit ``<2.0``. A stable version
    gets the same answer as with the default matching of ``packaging``.

    ``supported_versions`` that is not a valid range raises
    ``packaging.specifiers.InvalidSpecifier``.

    See https://peps.python.org/pep-0440/#handling-of-pre-releases.
    """
    return SpecifierSet(supported_versions).contains(version, prereleases=True)
