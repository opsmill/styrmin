"""The post-processor's planning: segments, labels and ffmpeg arguments (research R-005)."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from tests.e2e.demos.video import (
    Cut,
    Segment,
    Wait,
    ffmpeg_arguments,
    format_duration,
    label_text,
    plan_segments,
    planned_length,
)

R004_OUTPUT_OPTIONS = [
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    "18",
    "-pix_fmt",
    "yuv420p",
    "-r",
    "30",
    "-movflags",
    "+faststart",
    "-an",
]


def _final_length(segment: Segment) -> float:
    return (segment.end - segment.start) / segment.factor


def _assert_covers(segments: list[Segment], raw_duration: float) -> None:
    assert segments[0].start == 0.0
    assert segments[-1].end == raw_duration
    for previous, following in pairwise(segments):
        assert previous.end == following.start


def test_plan_segments_covers_the_raw_video_without_gap_or_overlap() -> None:
    waits = [Wait("Infrahub is starting", 5.0, 65.0), Wait("Task runs", 80.0, 83.0)]
    cuts = [Cut(90.0, 100.0)]

    segments = plan_segments(waits, cuts, 120.0)

    _assert_covers(segments, 120.0)
    assert [segment.kind for segment in segments] == [
        "normal",
        "sped_up",
        "normal",
        "cut",
        "normal",
    ]


def test_plan_segments_keeps_a_wait_shorter_than_min_wait_at_normal_speed() -> None:
    segments = plan_segments([Wait("Task runs", 10.0, 15.9)], [], 30.0)

    _assert_covers(segments, 30.0)
    assert all(segment.kind == "normal" for segment in segments)
    assert all(segment.factor == 1 and segment.label is None for segment in segments)
    assert planned_length(segments) == pytest.approx(30.0)


def test_plan_segments_speeds_up_a_252_second_wait_to_4_seconds() -> None:
    segments = plan_segments(
        [Wait("Backup in progress", 10.0, 262.0)], [], 300.0, target=4.0
    )

    sped_up = [segment for segment in segments if segment.kind == "sped_up"]
    assert len(sped_up) == 1
    assert (sped_up[0].start, sped_up[0].end, sped_up[0].factor) == (10.0, 262.0, 63)
    assert _final_length(sped_up[0]) == pytest.approx(4.0)
    assert sped_up[0].label == "Sped up 63×: Backup in progress took 4 min 12 s"
    assert planned_length(segments) == pytest.approx(10.0 + 4.0 + 38.0)


def test_plan_segments_rounds_the_factor_up_so_a_wait_lasts_at_most_the_target() -> (
    None
):
    segments = plan_segments(
        [Wait("Infrahub is starting", 0.0, 9.0)], [], 9.0, target=4.0
    )

    assert segments[0].factor == 3
    assert _final_length(segments[0]) <= 4.0


def test_label_text_gives_the_factor_the_label_and_the_real_duration() -> None:
    assert (
        label_text("Backup in progress", 252.0, 63)
        == "Sped up 63×: Backup in progress took 4 min 12 s"
    )


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (252.0, "4 min 12 s"),
        (38.0, "38 s"),
        (38.4, "38 s"),
        (120.0, "2 min"),
        (59.6, "1 min"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_plan_segments_gives_a_cut_segment_that_planned_length_leaves_out() -> None:
    segments = plan_segments([], [Cut(20.0, 30.0)], 60.0)

    _assert_covers(segments, 60.0)
    assert [(segment.start, segment.end, segment.kind) for segment in segments] == [
        (0.0, 20.0, "normal"),
        (20.0, 30.0, "cut"),
        (30.0, 60.0, "normal"),
    ]
    assert planned_length(segments) == pytest.approx(50.0)


@pytest.mark.parametrize(
    ("waits", "cuts"),
    [
        pytest.param(
            [Wait("A", 0.0, 10.0), Wait("B", 5.0, 15.0)], [], id="overlapping-waits"
        ),
        pytest.param(
            [Wait("A", 0.0, 10.0)], [Cut(8.0, 12.0)], id="wait-overlapping-a-cut"
        ),
        pytest.param(
            [Wait("A", 20.0, 30.0), Wait("B", 0.0, 10.0)], [], id="waits-out-of-order"
        ),
        pytest.param([], [Cut(20.0, 30.0), Cut(0.0, 10.0)], id="cuts-out-of-order"),
        pytest.param([Wait("A", -1.0, 10.0)], [], id="wait-before-the-start"),
        pytest.param(
            [Wait("A", 50.0, 61.5)], [], id="wait-ending-over-1-s-after-the-end"
        ),
        pytest.param([Wait("A", 60.0, 60.5)], [], id="wait-starting-at-the-end"),
    ],
)
def test_plan_segments_rejects_invalid_waits_and_cuts(
    waits: list[Wait], cuts: list[Cut]
) -> None:
    with pytest.raises(ValueError):
        plan_segments(waits, cuts, 60.0)


def test_plan_segments_clips_a_wait_ending_up_to_1_second_after_the_raw_duration() -> (
    None
):
    segments = plan_segments([Wait("Infrahub answers", 50.0, 61.0)], [], 60.0)

    _assert_covers(segments, 60.0)
    assert (segments[-1].kind, segments[-1].start, segments[-1].end) == (
        "sped_up",
        50.0,
        60.0,
    )
    assert segments[-1].label == "Sped up 3×: Infrahub answers took 10 s"


def test_plan_segments_leaves_no_kept_part_shorter_than_a_tenth_of_a_second() -> None:
    # A cut that starts right after a wait ends must not leave a part that holds no frame.
    segments = plan_segments(
        [Wait("Clone in progress", 10.0, 70.0)], [Cut(70.00005, 80.0)], 90.0
    )

    _assert_covers(segments, 90.0)
    assert [segment.kind for segment in segments] == [
        "normal",
        "sped_up",
        "cut",
        "normal",
    ]
    assert all(
        segment.end - segment.start >= 0.1
        for segment in segments
        if segment.kind != "cut"
    )
    assert (segments[1].end, segments[1].factor, segments[2].start) == (70.0, 15, 70.0)


def test_plan_segments_joins_a_short_first_or_last_part_to_its_neighbour() -> None:
    segments = plan_segments([Wait("Infrahub is starting", 0.05, 60.0)], [], 60.04)

    _assert_covers(segments, 60.04)
    assert [segment.kind for segment in segments] == ["sped_up"]


def test_wait_and_cut_reject_an_end_that_is_not_after_the_start() -> None:
    with pytest.raises(ValueError):
        Wait("A", 10.0, 10.0)
    with pytest.raises(ValueError):
        Cut(10.0, 9.0)


def test_ffmpeg_arguments_for_a_normal_a_sped_up_and_a_cut_segment() -> None:
    segments = plan_segments(
        [Wait("Backup in progress", 10.0, 262.0)], [Cut(262.0, 270.0)], 270.0
    )
    assert [segment.kind for segment in segments] == ["normal", "sped_up", "cut"]

    arguments = ffmpeg_arguments(
        Path("raw.webm"), segments, [Path("label-0.png")], Path("out.mp4")
    )

    assert arguments.count("-i") == 3
    first_input = arguments.index("-ss")
    assert arguments[first_input : first_input + 14] == [
        *("-ss", "0.000", "-to", "10.000", "-i", "raw.webm"),
        *("-ss", "10.000", "-to", "262.000", "-i", "raw.webm"),
        *("-i", "label-0.png"),
    ]
    graph = arguments[arguments.index("-filter_complex") + 1]
    assert graph == (
        "[0:v]setpts=PTS-STARTPTS[v0];"
        "[1:v]setpts=(PTS-STARTPTS)/63[s1];"
        "[s1][2:v]overlay=(W-w)/2:H-h-64[v1];"
        "[v0][v1]concat=n=2:v=1:a=0,fps=30,format=yuv420p[out]"
    )
    output = arguments.index("-map")
    assert arguments[output:] == ["-map", "[out]", *R004_OUTPUT_OPTIONS, "out.mp4"]


def test_ffmpeg_arguments_rejects_a_label_count_that_differs_from_the_sped_up_segments() -> (
    None
):
    segments = plan_segments([Wait("Backup in progress", 10.0, 262.0)], [], 270.0)

    with pytest.raises(ValueError):
        ffmpeg_arguments(Path("raw.webm"), segments, [], Path("out.mp4"))
