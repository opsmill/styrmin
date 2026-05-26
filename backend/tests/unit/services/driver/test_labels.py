"""Unit tests for ``format_driver_version_label``.

Covers the rendering matrix from spec 013 §FR-008 / User Story 4:

- local row (``content_hash`` populated, ``source_commit_sha`` null)
- git row (``source_commit_sha`` populated, ``content_hash`` null)
- legacy fallback (both null) — bare version
- defensive: both set → ``content_hash`` wins
- empty-string fingerprint behaves like null (falsy)
- fingerprint of exactly 7 characters is sliced without out-of-bounds error
"""

from styrmin_backend.services.driver.labels import format_driver_version_label


def test_local_row_renders_first_seven_chars_of_content_hash() -> None:
    label = format_driver_version_label(
        version="1.2.3",
        content_hash="a" * 64,
        source_commit_sha=None,
    )
    assert label == "1.2.3@aaaaaaa"


def test_git_row_renders_first_seven_chars_of_commit_sha() -> None:
    label = format_driver_version_label(
        version="1.2.3",
        content_hash=None,
        source_commit_sha="b" * 40,
    )
    assert label == "1.2.3@bbbbbbb"


def test_both_null_falls_back_to_bare_version() -> None:
    label = format_driver_version_label(
        version="1.2.3",
        content_hash=None,
        source_commit_sha=None,
    )
    assert label == "1.2.3"


def test_both_set_content_hash_wins() -> None:
    label = format_driver_version_label(
        version="1.2.3",
        content_hash="c" * 64,
        source_commit_sha="d" * 40,
    )
    assert label == "1.2.3@ccccccc"


def test_empty_string_fingerprints_behave_like_null() -> None:
    label = format_driver_version_label(
        version="1.2.3",
        content_hash="",
        source_commit_sha="",
    )
    assert label == "1.2.3"


def test_exactly_seven_char_fingerprint_is_handled_without_error() -> None:
    label = format_driver_version_label(
        version="1.2.3",
        content_hash="abcdef0",
        source_commit_sha=None,
    )
    assert label == "1.2.3@abcdef0"
