# ADR-083: Each Demo Is Recorded as One Screencast, and ffmpeg Speeds Up Its Waits After the Recording

**Status**: Accepted
**Date**: 2026-10-21
**Decision-makers**: Fatih Acar
**Source**: specs/archive/031-recorded-feature-demos/research.md ("Third-party dependency
evaluation", R-001 to R-005, R-016), specs/archive/031-recorded-feature-demos/spec.md (FR-004,
FR-005, FR-007, FR-020, FR-021, FR-024; SC-002, SC-003),
specs/archive/031-recorded-feature-demos/spike-notes.md ("One screencast records both origins");
[issue #518](https://github.com/opsmill/styrmin/issues/518); [PR #540](https://github.com/opsmill/styrmin/pull/540)
**Related**: [ADR-082](0082-recorded-demos-reuse-e2e-page-objects.md) (the demos act through the
E2E page objects)

## Context

Each recorded demo waits for the cluster several times: for a deployment to reach Running, for an
upgrade or update task, for an environment backup, restore or clone, and for an application to
answer again. The E2E suite allows up to 300 seconds for a backup and 600 seconds for a restore. A
video for the beta presentation has to last 3 minutes or less (SC-002), and must not suggest that an
operation is faster than it is (FR-005). The video also shows a title at the start of each step and
a cursor and a highlight on each action (FR-004), and plays in Keynote, PowerPoint and Google Slides
(SC-003).

Playwright's Screencast API records a page with chapters, a cursor and action highlights, but it
cannot pause and resume. The upstream request for pause and resume,
[microsoft/playwright#41178](https://github.com/microsoft/playwright/issues/41178), was closed as
"not planned" on 2026-06-08. The extension point that the maintainer named is the `on_frame`
callback with your own encoder.

## Decision drivers

- The viewer sees each wait happen, sped up, with its real duration.
- The video's length does not depend on how long the cluster takes.
- The encoding works with any ffmpeg build that has libx264, including Homebrew's on macOS.
- A failed encoding does not cost a new recording, which takes up to about 10 minutes for one demo.

## Considered options

1. Record continuously, record the start and end of each wait, and speed up those parts with ffmpeg
   after the recording.
2. Stop the screencast during each wait and join the files.
3. Encode the frames in the recorder with the `on_frame` callback.

## Decision

We chose option 1.

**Recording.** The recorder uses Playwright 1.64 (`playwright>=1.64,<1.65` in the root dev group).
1.64 is the first version whose cursor stays visible after the page loads a new URL, and the page
objects call `page.goto` before most actions. For each demo, the recorder:

- logs in to Styrmin on the page it will record before it calls `page.screencast.start(path,
  size=1920×1080)`, in a browser context with a 1920×1080 viewport;
- calls `show_actions(cursor="pointer", duration=800, style=...)`. Playwright 1.64 draws no highlight
  unless it gets a `style.highlight`, so the recorder passes a blue outline and hides the action
  title, which shows the Playwright locator;
- shows a chapter with `show_chapter(title, duration=2500)` at the start of each step;
- keeps a caption that names the application on screen and its environment, with `show_overlay`
  (FR-020);
- records one screencast for Styrmin, Infrahub and Semaphore. On 2026-10-18, one screencast kept
  recording across a navigation to another origin, with the cursor still visible after it.

**Waits and cuts.** The demo script wraps each call that blocks until the cluster or an application
reaches a state in `recorder.wait(label)`. The recorder records its start and end in seconds since
the screencast started, with `time.monotonic()`. Two other blocks record a cut, a part that the
video leaves out:

- `recorder.unrecorded()` yields a second page of the same browser context. The recorder logs in to
  Infrahub and Semaphore there, so the recorded page is logged in too, because cookies and
  `localStorage` are shared by the pages of a context. Logins to an application that exists only
  after a recorded step, such as the clone's Infrahub and Semaphore in demo 4, happen during the
  recording, and their time is cut.
- `recorder.cut()` cuts a block on the recorded page.

**Planning.** After `stop()`, the pure function `plan_segments(waits, cuts, raw_duration, *,
min_wait=6.0, target=4.0)` in `backend/tests/e2e/demos/video.py` returns segments that cover the raw
video with no gap:

- a wait shorter than `min_wait` seconds stays at normal speed;
- a longer wait becomes a sped-up segment with `factor = ceil(duration / target)`, at least 2, so it
  lasts at most `target` seconds in the video;
- a cut becomes a segment that the video leaves out;
- the parts between them play at normal speed.

The command saves the segments, the chapters and the closing card as `plan.json` next to `raw.webm`
in the demo's work directory before it encodes. When the encoding fails, it keeps that directory,
and `uv run invoke record --encode-again <directory>` encodes it without recording again (FR-024).

**Labels.** Each sped-up segment shows a label such as "The upgrade runs (2 min 55 s, shown 44×
faster)". The recorder renders each label as a PNG with its own browser, on a new page that the
screencast does not record (`page.set_content`, then `locator.screenshot(omit_background=True)`),
and ffmpeg places it with the `overlay` filter. The closing card is rendered the same way.

**Encoding.** A pure function builds the ffmpeg arguments from the plan. Each segment is its own
input, cut with input seeking (`-ss start -to end -i raw.webm`), so ffmpeg does not keep every frame
in memory. Each input gets `setpts=(PTS-STARTPTS)/factor`, and the inputs are joined with `concat`,
then `fps=30,format=yuv420p`. The output is H.264 at 1920×1080:
`-c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -r 30 -movflags +faststart -an`. The video and
its chapter file are written under a temporary name and then renamed.

## Consequences

- Good, because the viewer sees each wait, with the progress on the page, and its label gives the
  real duration and the factor.
- Good, because each wait lasts at most 4 seconds in the video, so the length of a video is about its
  active time plus 4 seconds for each wait. The summary warns when a video is longer than 3:00; the
  fix then goes into the demo script (fewer or shorter steps), not into a larger factor.
- Good, because the planning and the ffmpeg arguments are pure functions with unit tests, and only
  `encode.py` runs ffmpeg.
- Good, because the labels need no optional ffmpeg library and use the same fonts as the chapter
  titles. `drawtext` needs ffmpeg built with libfreetype and libharfbuzz, which Homebrew's `ffmpeg`
  9.0.2 does not have since [Homebrew/homebrew-core#261303](https://github.com/Homebrew/homebrew-core/pull/261303).
- Bad, because Playwright writes WebM with frame times that follow when the browser showed each
  frame, so cuts must use times, not frame numbers.
- Bad, because each chapter adds about 2.8 s to the video: `show_chapter` returns after its duration
  plus a 300 ms fade. Each action is held for 800 ms, which slows the script.
- Not checked yet: whether the videos play in Keynote, PowerPoint and Google Slides without
  conversion (SC-003). The settings follow what Microsoft, Apple and Google document for H.264 MP4.

Option 2 was rejected because the viewer would not see the progress during a wait, and the PRD asks
for the wait to be visible and labelled. Option 3 was rejected because it moves video encoding into
the recorder, and the real duration of a wait is known only when it ends, so the factor cannot be
chosen while the frames arrive. `show_overlay` for the sped-up labels was rejected for the same
reason.

## Confirmation

- `backend/tests/unit/demos/test_video.py`: the segments cover the raw video with no gap or overlap;
  a wait shorter than `min_wait` stays at normal speed; a 252-second wait becomes 4 seconds; a cut is
  left out; overlapping waits and cuts are refused; the ffmpeg arguments for a normal, a sped-up and
  a cut segment and the closing card; a video plan survives its JSON.
- `backend/tests/unit/demos/test_encode.py`: `encode_video` gives an H.264 video of the planned
  length and size, and leaves no video when ffmpeg fails.
- `backend/tests/unit/demos/test_recorder.py`: the screencast starts at 1920×1080 with the pointer and
  a highlight; waits and cuts are recorded in seconds since the start and cannot nest.

## More information

[Videos and files the command writes](../guides/local-demo.md#videos-and-files-the-command-writes)
in the local demo guide.
