"""``styrmin-driver``: check, render and compare an application driver on the author's machine.

The commands read files only. They need no Styrmin server, database, cluster or network
access. The interface is specs/032-styrmin-driver-cli/contracts/cli.md.

Exit codes: 0 when the driver passes or the values are the same, 1 when the driver has
errors or the values differ, 2 when the command cannot run.
"""

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TextIO

import yaml

from styrmin_sdk.driver_format.diagnostics import TEMPLATE_CHECKS, CheckReport, Diagnostic, run_checks
from styrmin_sdk.driver_format.diff import compare_values
from styrmin_sdk.driver_format.example_context import ContextFileError

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2
PROG = "styrmin-driver"


class _CannotRunError(Exception):
    """The command cannot run (exit code 2).

    The driver path does not exist or is not a directory, or a context or base file cannot
    be read, is not UTF-8, is not valid YAML, or gives a context that does not match the
    context model.
    """


def _package_version() -> str:
    try:
        return version("styrmin-sdk")
    except PackageNotFoundError:
        return "unknown"


def _print(message: str, stream: TextIO) -> None:
    stream.write(message + "\n")


def _driver_root(value: str) -> Path:
    root = Path(value)
    if not root.exists():
        raise _CannotRunError(f"the driver directory does not exist: {value}")
    if not root.is_dir():
        raise _CannotRunError(f"the driver path is not a directory: {value}")
    return root


def _read_yaml_file(value: str, what: str) -> object:
    try:
        data = Path(value).read_bytes()
    except OSError as err:
        raise _CannotRunError(f"the {what} cannot be read: {value}: {err.strerror or err}") from err
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise _CannotRunError(f"the {what} is not valid UTF-8: {value}: {err.reason} at byte {err.start}") from err
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise _CannotRunError(f"the {what} is not valid YAML: {value}: {err}") from err


def _context_data(args: argparse.Namespace) -> object | None:
    if args.context is None:
        return None
    return _read_yaml_file(args.context, "context file")


def _run(args: argparse.Namespace, *, check_actions: bool) -> CheckReport:
    root = _driver_root(args.dir)
    try:
        return run_checks(root, display_root=args.dir, context_data=_context_data(args), check_actions=check_actions)
    except ContextFileError as err:
        lines = [f"{path}: {message}" if path else message for path, message in err.problems]
        raise _CannotRunError("\n".join(f"context file {args.context}: {line}" for line in lines)) from err


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _summary(dir_label: str, report: CheckReport) -> str:
    if not report.diagnostics:
        return f"{dir_label}: no errors"
    return f"{dir_label}: {_plural(len(report.errors), 'error')}, {_plural(len(report.warnings), 'warning')}"


def _print_diagnostics(diagnostics: list[Diagnostic], stream: TextIO) -> None:
    for diagnostic in diagnostics:
        _print(diagnostic.format(), stream)


def _cmd_check(args: argparse.Namespace) -> int:
    report = _run(args, check_actions=True)
    _print_diagnostics(report.diagnostics, sys.stdout)
    _print(_summary(args.dir, report), sys.stdout)
    return EXIT_FAILED if report.errors else EXIT_OK


def _rendered_values(args: argparse.Namespace) -> tuple[CheckReport, object | None]:
    """Run the checks that a render needs; the values are None when the driver has errors."""
    report = _run(args, check_actions=False)
    _print_diagnostics(report.diagnostics, sys.stderr)
    if report.errors or report.rendered is None:
        return report, None
    return report, report.rendered.values


def _cmd_render(args: argparse.Namespace) -> int:
    report, values = _rendered_values(args)
    if report.errors or report.rendered is None:
        return EXIT_FAILED
    sys.stdout.write(yaml.safe_dump(values, sort_keys=False, default_flow_style=False))
    return EXIT_OK


def _cmd_diff(args: argparse.Namespace) -> int:
    base = _read_yaml_file(args.base, "base values file")
    report, values = _rendered_values(args)
    if report.errors or report.rendered is None:
        return EXIT_FAILED
    lines = compare_values(base, values, base_label=args.base, rendered_label=f"rendered {args.dir}")
    sys.stdout.writelines(lines)
    return EXIT_FAILED if lines else EXIT_OK


def _cmd_context(args: argparse.Namespace) -> int:
    report = _run(args, check_actions=False)
    # A problem of the values template does not change the context, so it is left out.
    relevant = [d for d in report.diagnostics if d.check not in TEMPLATE_CHECKS]
    _print_diagnostics(relevant, sys.stderr)
    if any(d.severity == "error" for d in relevant) or report.context is None:
        return EXIT_FAILED
    data = report.context.model_dump(mode="json", exclude_none=True)
    sys.stdout.write(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Check, render and compare a Styrmin application driver on your machine, "
            "with no Styrmin server, database or cluster."
        ),
        epilog="Exit codes: 0 passed or same values, 1 driver errors or values differ, 2 the command cannot run.",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {_package_version()}")
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.required = True

    def add(name: str, help_text: str, *, base: bool = False) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument("dir", help="the driver directory, which holds driver.styrmin.yml")
        command.add_argument(
            "--context",
            metavar="FILE",
            help="a YAML or JSON file with the context values to change; merged into the example context",
        )
        if base:
            command.add_argument("--base", metavar="FILE", required=True, help="the Helm values to compare with")
        return command

    add("check", "Run the checks of a driver load, then render values.j2.yml.").set_defaults(func=_cmd_check)
    add("render", "Render values.j2.yml and write the Helm values to standard output.").set_defaults(func=_cmd_render)
    add("diff", "Compare the rendered Helm values with a saved values file.", base=True).set_defaults(func=_cmd_diff)
    add("context", "Write the example context, merged with --context, to standard output.").set_defaults(
        func=_cmd_context
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run ``styrmin-driver`` with ``argv`` (default: the process arguments) and return the exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_CANNOT_RUN
    try:
        return args.func(args)
    except _CannotRunError as err:
        for line in str(err).splitlines():
            _print(f"{PROG}: error: {line}", sys.stderr)
        return EXIT_CANNOT_RUN
    except Exception as err:  # noqa: BLE001 - a crash must not read as "the driver has errors" (1)
        _print(f"{PROG}: internal error: {type(err).__name__}: {err}", sys.stderr)
        return EXIT_CANNOT_RUN


if __name__ == "__main__":
    sys.exit(main())
