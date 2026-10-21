"""The post-processor's planning: segments, labels and ffmpeg arguments (research R-005)."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from tests.e2e.demos.video import (
    Chapter,
    ClosingCard,
    Cut,
    Segment,
    VideoPlan,
    Wait,
    chapter_lines,
    ffmpeg_arguments,
    final_time,
    format_duration,
    format_timestamp,
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
    assert sped_up[0].label == "Backup in progress (4 min 12 s, shown 63× faster)"
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
        label_text("The backup runs", 252.0, 63)
        == "The backup runs (4 min 12 s, shown 63× faster)"
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
    assert segments[-1].label == "Infrahub answers (10 s, shown 3× faster)"


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


def test_ffmpeg_arguments_for_a_normal_a_sped_up_and_a_cut_segment_then_the_closing_card() -> (
    None
):
    segments = plan_segments(
        [Wait("Backup in progress", 10.0, 262.0)], [Cut(262.0, 270.0)], 270.0
    )
    assert [segment.kind for segment in segments] == ["normal", "sped_up", "cut"]

    arguments = ffmpeg_arguments(
        Path("raw.webm"),
        segments,
        [Path("label-0.png")],
        Path("out.mp4"),
        closing_card=Path("card.png"),
    )

    assert arguments.count("-i") == 4
    first_input = arguments.index("-ss")
    assert arguments[first_input : first_input + 22] == [
        *("-ss", "0.000", "-to", "10.000", "-i", "raw.webm"),
        *("-ss", "10.000", "-to", "262.000", "-i", "raw.webm"),
        *("-i", "label-0.png"),
        *("-loop", "1", "-framerate", "30", "-t", "6.000", "-i", "card.png"),
    ]
    graph = arguments[arguments.index("-filter_complex") + 1]
    assert graph == (
        "[0:v]setpts=PTS-STARTPTS,scale=1920:1080,setsar=1[v0];"
        "[1:v]setpts=(PTS-STARTPTS)/63,scale=1920:1080,setsar=1[s1];"
        "[s1][2:v]overlay=(W-w)/2:H-h-64[v1];"
        "[3:v]setpts=PTS-STARTPTS,scale=1920:1080,setsar=1[v2];"
        "[v0][v1][v2]concat=n=3:v=1:a=0,fps=30,format=yuv420p[out]"
    )
    output = arguments.index("-map")
    assert arguments[output:] == ["-map", "[out]", *R004_OUTPUT_OPTIONS, "out.mp4"]


def test_ffmpeg_arguments_rejects_a_label_count_that_differs_from_the_sped_up_segments() -> (
    None
):
    segments = plan_segments([Wait("Backup in progress", 10.0, 262.0)], [], 270.0)

    with pytest.raises(ValueError):
        ffmpeg_arguments(
            Path("raw.webm"), segments, [], Path("out.mp4"), closing_card=Path("c.png")
        )


def test_ffmpeg_arguments_rejects_a_closing_card_without_a_duration() -> None:
    segments = plan_segments([], [], 10.0)

    with pytest.raises(ValueError, match="closing card"):
        ffmpeg_arguments(
            Path("raw.webm"),
            segments,
            [],
            Path("out.mp4"),
            closing_card=Path("c.png"),
            closing_seconds=0.0,
        )


SEGMENTS = (
    Segment(0.0, 10.0, "normal"),
    Segment(
        10.0, 90.0, "sped_up", 20, "The upgrade runs (1 min 20 s, shown 20× faster)"
    ),
    Segment(90.0, 100.0, "cut"),
    Segment(100.0, 130.0, "normal"),
)


@pytest.mark.parametrize(
    ("raw_time", "expected"),
    [
        (0.0, 0.0),
        (5.0, 5.0),
        (10.0, 10.0),
        (50.0, 12.0),
        (90.0, 14.0),
        # A time inside a cut maps to the first frame after the cut.
        (95.0, 14.0),
        (100.0, 14.0),
        (130.0, 44.0),
    ],
)
def test_final_time_follows_the_sped_up_and_cut_segments(
    raw_time: float, expected: float
) -> None:
    assert final_time(raw_time, SEGMENTS) == pytest.approx(expected)


def test_chapter_lines_give_each_chapter_and_the_closing_card_in_the_final_video() -> (
    None
):
    plan = VideoPlan(
        video_name="1-deploy-upgrade.mp4",
        segments=SEGMENTS,
        chapters=(
            Chapter("Deploy Infrahub 1.10.11", 0.4),
            Chapter("Upgrade to Infrahub 1.11.7", 92.0),
            Chapter("The upgrade task and its steps", 125.0),
        ),
        closing=ClosingCard("Deploy and upgrade Infrahub", ()),
    )

    assert chapter_lines(plan) == [
        "0:00 Deploy Infrahub 1.10.11",
        "0:14 Upgrade to Infrahub 1.11.7",
        "0:39 The upgrade task and its steps",
        "0:44 Summary",
    ]


def test_format_timestamp_rounds_down_to_the_second() -> None:
    assert format_timestamp(59.9) == "0:59"
    assert format_timestamp(65.0) == "1:05"
    assert format_timestamp(600.0) == "10:00"


def test_a_video_plan_survives_its_json() -> None:
    plan = VideoPlan(
        video_name="4-clone.mp4",
        segments=SEGMENTS,
        chapters=(Chapter("Clone the environment", 3.5),),
        closing=ClosingCard("Clone an environment", ("A line.", "Another line.")),
    )

    assert VideoPlan.from_json(plan.to_json()) == plan


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "{}",
        '{"video_name": "x.mp4", "segments": [{"start": 0, "end": 1, "kind": "slow"}],'
        ' "chapters": [], "closing": {"title": "T", "lines": []}, "raw_name": "raw.webm"}',
    ],
)
def test_video_plan_from_json_refuses_what_is_not_a_plan(text: str) -> None:
    with pytest.raises(ValueError):
        VideoPlan.from_json(text)
