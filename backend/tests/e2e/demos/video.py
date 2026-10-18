"""Plan the final demo video from the recorded waits and cuts, and build its ffmpeg arguments (research R-005).

Pure functions only, unit tested without a browser or ffmpeg.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from operator import attrgetter
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

type SegmentKind = Literal["normal", "sped_up", "cut"]

# Waits are timed with time.monotonic(), not from the frames,
# so a wait can end just after the last frame.
END_TOLERANCE = 1.0
# A shorter kept part holds no frame: ffmpeg 6.1 then aborts
# or reads the input to its end.
SHORTEST_PART = 0.1
LABEL_BOTTOM_MARGIN = 64
OUTPUT_OPTIONS = (
    *("-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p"),
    *("-r", "30", "-movflags", "+faststart", "-an"),
)


def _check_range(start: float, end: float) -> None:
    if end <= start:
        raise ValueError(f"A range must end after it starts: start={start}, end={end}")


@dataclass(frozen=True)
class Wait:
    """A part of the recording during which the demo waits for the cluster, in seconds since it started."""

    label: str
    start: float
    end: float

    def __post_init__(self) -> None:
        _check_range(self.start, self.end)


@dataclass(frozen=True)
class Cut:
    """A part of the recording that the final video leaves out (research R-016)."""

    start: float
    end: float

    def __post_init__(self) -> None:
        _check_range(self.start, self.end)


@dataclass(frozen=True)
class Segment:
    """A part of the raw video and how the final video shows it."""

    start: float
    end: float
    kind: SegmentKind
    factor: int = 1
    label: str | None = None

    def __post_init__(self) -> None:
        _check_range(self.start, self.end)
        sped_up = self.kind == "sped_up"
        if sped_up != (self.factor > 1) or sped_up != (self.label is not None):
            raise ValueError(
                f"Only a sped_up segment has a factor above 1 and a label: {self}"
            )


@dataclass
class _Part:
    start: float
    end: float
    kind: SegmentKind
    wait_label: str | None = None


def format_duration(seconds: float) -> str:
    """Return a duration rounded to the second, for example ``"4 min 12 s"`` or ``"38 s"``."""
    if seconds < 0:
        raise ValueError(f"A duration cannot be negative: {seconds}")
    minutes, rest = divmod(round(seconds), 60)
    if minutes == 0:
        return f"{rest} s"
    if rest == 0:
        return f"{minutes} min"
    return f"{minutes} min {rest} s"


def label_text(label: str, real_seconds: float, factor: int) -> str:
    """Return the text shown on a sped-up part (research R-003)."""
    return f"Sped up {factor}×: {label} took {format_duration(real_seconds)}"


def planned_length(segments: Sequence[Segment]) -> float:
    """Return the length of the final video in seconds; cut segments add nothing."""
    return sum(
        (segment.end - segment.start) / segment.factor
        for segment in segments
        if segment.kind != "cut"
    )


def plan_segments(
    waits: Sequence[Wait],
    cuts: Sequence[Cut],
    raw_duration: float,
    *,
    min_wait: float = 6.0,
    target: float = 4.0,
) -> list[Segment]:
    """Return segments covering ``[0, raw_duration]``: long waits sped up to ``target`` seconds, cuts left out."""
    if raw_duration < SHORTEST_PART:
        raise ValueError(
            f"The raw video lasts {raw_duration} s, which is too short to plan"
        )
    if target <= 0:
        raise ValueError(
            f"The target length of a sped-up wait must be positive: {target}"
        )
    items = _checked_items(waits, cuts, raw_duration)
    parts = _absorb_short_parts(
        _merge_normal_parts(_parts(items, raw_duration, min_wait, target))
    )
    return [_segment(part, target) for part in parts]


def _checked_items(
    waits: Sequence[Wait], cuts: Sequence[Cut], raw_duration: float
) -> list[Wait | Cut]:
    for name, ranges in (("Waits", waits), ("Cuts", cuts)):
        for previous, following in pairwise(ranges):
            if following.start < previous.start:
                raise ValueError(
                    f"{name} are out of order: {previous} comes before {following}"
                )
    items: list[Wait | Cut] = sorted([*waits, *cuts], key=attrgetter("start"))
    for item in items:
        if (
            item.start < 0
            or item.start >= raw_duration
            or item.end > raw_duration + END_TOLERANCE
        ):
            raise ValueError(
                f"{item} is outside the raw video, which lasts {raw_duration} s"
            )
    for previous, following in pairwise(items):
        if following.start < previous.end:
            raise ValueError(f"{previous} overlaps {following}")
    return items


def _parts(
    items: Sequence[Wait | Cut], raw_duration: float, min_wait: float, target: float
) -> list[_Part]:
    parts: list[_Part] = []
    cursor = 0.0
    for item in items:
        if item.start > cursor:
            parts.append(_Part(cursor, item.start, "normal"))
        end = min(item.end, raw_duration)
        if isinstance(item, Cut):
            parts.append(_Part(item.start, end, "cut"))
        elif end - item.start < min_wait or end - item.start <= target:
            parts.append(_Part(item.start, end, "normal"))
        else:
            parts.append(_Part(item.start, end, "sped_up", item.label))
        cursor = end
    if cursor < raw_duration:
        parts.append(_Part(cursor, raw_duration, "normal"))
    return parts


def _merge_normal_parts(parts: Sequence[_Part]) -> list[_Part]:
    merged: list[_Part] = []
    for part in parts:
        if merged and part.kind == "normal" and merged[-1].kind == "normal":
            merged[-1].end = part.end
        else:
            merged.append(part)
    return merged


def _absorb_short_parts(parts: Sequence[_Part]) -> list[_Part]:
    # A normal part shorter than SHORTEST_PART joins a neighbouring cut,
    # else the part before it, else the next one.
    kept: list[_Part] = []
    for index, part in enumerate(parts):
        following = parts[index + 1] if index + 1 < len(parts) else None
        if part.kind != "normal" or part.end - part.start >= SHORTEST_PART:
            kept.append(part)
        elif kept and (
            kept[-1].kind == "cut" or following is None or following.kind != "cut"
        ):
            kept[-1].end = part.end
        elif following is not None:
            following.start = part.start
    return kept


def _segment(part: _Part, target: float) -> Segment:
    if part.kind != "sped_up" or part.wait_label is None:
        return Segment(part.start, part.end, part.kind)
    duration = part.end - part.start
    # Rounding first keeps float noise in the measured times
    # from adding 1 to the factor.
    factor = max(2, math.ceil(round(duration / target, 6)))
    return Segment(
        part.start,
        part.end,
        "sped_up",
        factor,
        label_text(part.wait_label, duration, factor),
    )


def ffmpeg_arguments(
    raw_path: Path,
    segments: Sequence[Segment],
    label_paths: Sequence[Path],
    output_path: Path,
) -> list[str]:
    """Return the ffmpeg arguments, without the program name, that encode ``segments`` of ``raw_path``.

    ``label_paths`` holds one label image per ``sped_up`` segment, in the order of those segments.
    """
    kept = [segment for segment in segments if segment.kind != "cut"]
    if not kept:
        raise ValueError("Every segment is cut, so the video would be empty")
    sped_up_count = sum(1 for segment in kept if segment.kind == "sped_up")
    if len(label_paths) != sped_up_count:
        raise ValueError(
            f"Got {len(label_paths)} label images for {sped_up_count} sped-up segments"
        )

    arguments = ["-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    for segment in kept:
        arguments += [
            "-ss",
            f"{segment.start:.3f}",
            "-to",
            f"{segment.end:.3f}",
            "-i",
            str(raw_path),
        ]
    for label_path in label_paths:
        arguments += ["-i", str(label_path)]

    filters: list[str] = []
    label_inputs = iter(range(len(kept), len(kept) + len(label_paths)))
    for index, segment in enumerate(kept):
        if segment.kind == "sped_up":
            filters.append(
                f"[{index}:v]setpts=(PTS-STARTPTS)/{segment.factor}[s{index}]"
            )
            overlay = f"overlay=(W-w)/2:H-h-{LABEL_BOTTOM_MARGIN}"
            filters.append(f"[s{index}][{next(label_inputs)}:v]{overlay}[v{index}]")
        else:
            filters.append(f"[{index}:v]setpts=PTS-STARTPTS[v{index}]")
    joined = "".join(f"[v{index}]" for index in range(len(kept)))
    filters.append(f"{joined}concat=n={len(kept)}:v=1:a=0,fps=30,format=yuv420p[out]")

    return [
        *arguments,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        *OUTPUT_OPTIONS,
        str(output_path),
    ]
