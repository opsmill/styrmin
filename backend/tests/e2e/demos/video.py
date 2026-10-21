"""Plan the final demo video from the recorded waits, cuts and chapters, and build its ffmpeg arguments (research R-005).

Pure functions only, unit tested without a browser or ffmpeg.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from itertools import pairwise
from operator import attrgetter
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

type SegmentKind = Literal["normal", "sped_up", "cut"]
SEGMENT_KINDS = ("normal", "sped_up", "cut")

# Waits are timed with time.monotonic(), not from the frames,
# so a wait can end just after the last frame.
END_TOLERANCE = 1.0
# A shorter kept part holds no frame: ffmpeg 6.1 then aborts
# or reads the input to its end.
SHORTEST_PART = 0.1
# The label stays above the caption that the recorder keeps in the bottom left corner, which ends
# 72 px above the bottom (recorder._CAPTION_HTML).
LABEL_BOTTOM_MARGIN = 112
VIDEO_SIZE = (1920, 1080)
# How long the closing card stays on screen at the end of each video.
CLOSING_SECONDS = 6.0
RAW_NAME = "raw.webm"
CLOSING_CHAPTER = "Summary"
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
        if self.kind not in SEGMENT_KINDS:
            raise ValueError(f"Unknown segment kind {self.kind!r}: {self}")
        sped_up = self.kind == "sped_up"
        if sped_up != (self.factor > 1) or sped_up != (self.label is not None):
            raise ValueError(
                f"Only a sped_up segment has a factor above 1 and a label: {self}"
            )


@dataclass(frozen=True)
class Chapter:
    """A step title and when the step started, in seconds since the recording started."""

    title: str
    start: float


@dataclass(frozen=True)
class ClosingCard:
    """The card that ends each video: the demo's title and what the video showed."""

    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class VideoPlan:
    """What the encoder needs besides the raw video, saved as JSON next to it so that a failed encoding can run again.

    ``chapters`` hold times of the raw video; ``video_name`` is the name of the MP4 file, for example
    ``1-deploy-upgrade.mp4``.
    """

    video_name: str
    segments: tuple[Segment, ...]
    chapters: tuple[Chapter, ...]
    closing: ClosingCard
    raw_name: str = RAW_NAME

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> VideoPlan:
        """Read a plan that ``to_json`` wrote; raise ``ValueError`` when ``text`` is not one."""
        try:
            data = json.loads(text)
            return cls(
                video_name=data["video_name"],
                segments=tuple(Segment(**segment) for segment in data["segments"]),
                chapters=tuple(Chapter(**chapter) for chapter in data["chapters"]),
                closing=ClosingCard(
                    title=data["closing"]["title"],
                    lines=tuple(data["closing"]["lines"]),
                ),
                raw_name=data["raw_name"],
            )
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"Not a video plan: {error!r}") from None


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
    """Return the text shown on a sped-up part (research R-003), for example
    ``"The upgrade runs (2 min 55 s, shown 44× faster)"``."""
    return f"{label} ({format_duration(real_seconds)}, shown {factor}× faster)"


def format_timestamp(seconds: float) -> str:
    """Return a position in the video rounded down to the second, for example ``"1:05"``."""
    minutes, rest = divmod(math.floor(seconds), 60)
    return f"{minutes}:{rest:02d}"


def planned_length(segments: Sequence[Segment]) -> float:
    """Return the length of the final video in seconds; cut segments add nothing."""
    return sum(
        (segment.end - segment.start) / segment.factor
        for segment in segments
        if segment.kind != "cut"
    )


def final_time(raw_time: float, segments: Sequence[Segment]) -> float:
    """Return where ``raw_time`` of the raw video plays in the final video.

    A time inside a cut maps to the first frame after the cut.
    """
    elapsed = 0.0
    for segment in segments:
        if raw_time <= segment.start:
            break
        if segment.kind != "cut":
            elapsed += (min(raw_time, segment.end) - segment.start) / segment.factor
    return elapsed


def chapter_lines(plan: VideoPlan) -> list[str]:
    """Return one line per chapter of the final video, then one for the closing card, for example ``"0:14 Upgrade"``."""
    lines = [
        f"{format_timestamp(final_time(chapter.start, plan.segments))} {chapter.title}"
        for chapter in plan.chapters
    ]
    lines.append(f"{format_timestamp(planned_length(plan.segments))} {CLOSING_CHAPTER}")
    return lines


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
    *,
    closing_card: Path,
    closing_seconds: float = CLOSING_SECONDS,
    size: tuple[int, int] = VIDEO_SIZE,
) -> list[str]:
    """Return the ffmpeg arguments, without the program name, that encode ``segments`` of ``raw_path``, then
    ``closing_card`` for ``closing_seconds``, at ``size``.

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
    if closing_seconds <= 0:
        raise ValueError(
            f"The closing card must last a positive time: {closing_seconds}"
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
    card_input = len(kept) + len(label_paths)
    arguments += [
        *("-loop", "1", "-framerate", "30", "-t", f"{closing_seconds:.3f}"),
        *("-i", str(closing_card)),
    ]

    # Every part gets the same size and square pixels, which the concat filter requires.
    width, height = size
    fit = f"scale={width}:{height},setsar=1"
    filters: list[str] = []
    label_inputs = iter(range(len(kept), card_input))
    for index, segment in enumerate(kept):
        if segment.kind == "sped_up":
            filters.append(
                f"[{index}:v]setpts=(PTS-STARTPTS)/{segment.factor},{fit}[s{index}]"
            )
            overlay = f"overlay=(W-w)/2:H-h-{LABEL_BOTTOM_MARGIN}"
            filters.append(f"[s{index}][{next(label_inputs)}:v]{overlay}[v{index}]")
        else:
            filters.append(f"[{index}:v]setpts=PTS-STARTPTS,{fit}[v{index}]")
    card = len(kept)
    filters.append(f"[{card_input}:v]setpts=PTS-STARTPTS,{fit}[v{card}]")
    joined = "".join(f"[v{index}]" for index in range(card + 1))
    filters.append(f"{joined}concat=n={card + 1}:v=1:a=0,fps=30,format=yuv420p[out]")

    return [
        *arguments,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        *OUTPUT_OPTIONS,
        str(output_path),
    ]
