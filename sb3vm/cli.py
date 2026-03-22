from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sb3vm.codegen import CodegenError, build_project, export_project_source, load_authoring_module, run_authored_project, save_authored_project
from sb3vm.io.load_sb3 import load_sb3
from sb3vm.io.save_sb3 import save_sb3
from sb3vm.log import configure_logging, debug, error, fatal, get_logger, info
from sb3vm.parse.pretty import render_project_text
from sb3vm.render import MinimalRenderer, RendererError
from sb3vm.vm.compat import default_manifest_path, run_compat_suite
from sb3vm.vm.benchmark import run_benchmark_case
from sb3vm.vm.errors import ProjectValidationError, Sb3VmError
from sb3vm.vm.runtime import Sb3Vm


_LOGGER = get_logger(__name__)


def cmd_inspect(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.inspect", "inspecting project %s", args.path)
    project = load_sb3(args.path)
    vm = Sb3Vm(project)
    print(json.dumps(vm.inspect(), indent=2, sort_keys=True))
    return 0


def cmd_resave(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.resave", "resaving project %s -> %s", args.input, args.output)
    project = load_sb3(args.input)
    save_sb3(project, args.output)
    print(f"resaved {args.input} -> {args.output}")
    return 0


def cmd_text(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.text", "rendering text view for %s", args.path)
    project = load_sb3(args.path)
    print(render_project_text(project), end="")
    return 0


def _print_run_status(vm: Sb3Vm, step: int, total_steps: int) -> None:
    statuses = vm.thread_statuses()
    print(f"[step {step}/{total_steps}] t={vm.state.time_seconds:.3f}s threads={len(statuses)} clones={vm.state.live_clone_count()}")
    if not statuses:
        print("  idle")
        return
    for status in statuses:
        wait = ""
        if status["wait_state"]:
            wait = f" wait={status['wait_state']}"
            if status["wait_detail"]:
                wait += f"({status['wait_detail']})"
        stmt = status["current_statement"] or "<idle>"
        print(
            f"  T{status['thread_id']} {status['target_name']}#{status['instance_id']} "
            f"trigger={status['root_trigger']} stmt={stmt}{wait}"
        )


def cmd_run(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.run", "running %s for %.3fs dt=%.5f status=%s", args.path, args.seconds, args.dt, args.status)
    project = load_sb3(args.path)
    vm = Sb3Vm(project)
    if args.status:
        total_steps = max(0, int(args.seconds / args.dt))
        vm.start_green_flag()
        _print_run_status(vm, 0, total_steps)
        for step in range(1, total_steps + 1):
            vm.step(args.dt)
            _print_run_status(vm, step, total_steps)
    else:
        vm.run_for(args.seconds, dt=args.dt)
    print(json.dumps(vm.snapshot(), indent=2, sort_keys=True))
    return 0


def cmd_run_display(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.run_display", "running display renderer for %s", args.path)
    project = load_sb3(args.path)
    vm = Sb3Vm(project)
    renderer = MinimalRenderer(project, vm, scale=args.scale, fps=args.fps)
    renderer.run(seconds=args.seconds, dt=args.dt)
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.benchmark", "benchmarking %s as %s", args.path, args.name or args.path.stem)
    project = load_sb3(args.path)
    result = run_benchmark_case(args.name or args.path.stem, project, seconds=args.seconds, dt=args.dt)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


def cmd_compat(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.compat", "running compat suite manifest=%s projects_dir=%s", args.manifest, args.projects_dir)
    report = run_compat_suite(
        manifest_path=args.manifest,
        extra_projects_dir=args.projects_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if args.fail_on_regression and report["summary"]["regression_count"] > 0 else 0


def cmd_py_scaffold(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.py_scaffold", "writing scaffold %s", args.path)
    target = args.path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        """from sb3vm.codegen import ScratchProject, broadcast_wait

project = ScratchProject("Demo Authoring Project")
stage = project.stage
hero = project.sprite("Hero", x=0, y=0)
score = stage.variable("score", 0)

@stage.when_flag_clicked()
def main():
    score = 1
    for _ in range(3):
        score += 2
    broadcast_wait("go")

@hero.when_broadcast_received("go")
def on_go():
    pass
""",
        encoding="utf-8",
    )
    print(str(target))
    return 0


def cmd_py_build(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.py_build", "building authored project %s -> %s", args.source, args.output)
    save_authored_project(args.source, args.output, project_attr=args.project_attr)
    print(f"built {args.source} -> {args.output}")
    return 0


def cmd_py_export(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.py_export", "exporting %s -> %s", args.input, args.output)
    project = load_sb3(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(export_project_source(project), encoding="utf-8")
    print(f"exported {args.input} -> {args.output}")
    return 0


def cmd_py_run(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.py_run", "running authored source %s", args.source)
    _, vm = run_authored_project(args.source, project_attr=args.project_attr, seconds=args.seconds, dt=args.dt)
    print(json.dumps(vm.snapshot(), indent=2, sort_keys=True))
    return 0


def cmd_py_inspect(args: argparse.Namespace) -> int:
    info(_LOGGER, "cli.py_inspect", "inspecting authored source %s", args.source)
    project = build_project(args.source, project_attr=args.project_attr)
    vm = Sb3Vm(project)
    payload = {
        "authoring_module": str(args.source),
        "project": project.to_json(),
        "vm_inspect": vm.inspect(),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sb3vm.cli")
    parser.add_argument("--log-level", type=str, default=None, help="Set log level: TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_p = sub.add_parser("inspect")
    inspect_p.add_argument("path", type=Path)
    inspect_p.set_defaults(func=cmd_inspect)

    text_p = sub.add_parser("text")
    text_p.add_argument("path", type=Path)
    text_p.set_defaults(func=cmd_text)

    resave_p = sub.add_parser("resave")
    resave_p.add_argument("input", type=Path)
    resave_p.add_argument("output", type=Path)
    resave_p.set_defaults(func=cmd_resave)

    run_p = sub.add_parser("run")
    run_p.add_argument("path", type=Path)
    run_p.add_argument("--seconds", type=float, default=1.0)
    run_p.add_argument("--dt", type=float, default=1 / 30)
    run_p.add_argument("--status", action="store_true")
    run_p.set_defaults(func=cmd_run)

    display_p = sub.add_parser("run-display")
    display_p.add_argument("path", type=Path)
    display_p.add_argument("--seconds", type=float, default=None)
    display_p.add_argument("--dt", type=float, default=1 / 30)
    display_p.add_argument("--fps", type=int, default=30)
    display_p.add_argument("--scale", type=float, default=1.0)
    display_p.set_defaults(func=cmd_run_display)

    bench_p = sub.add_parser("benchmark")
    bench_p.add_argument("path", type=Path)
    bench_p.add_argument("--seconds", type=float, default=1.0)
    bench_p.add_argument("--dt", type=float, default=1 / 30)
    bench_p.add_argument("--name", type=str, default=None)
    bench_p.set_defaults(func=cmd_benchmark)

    compat_p = sub.add_parser("compat")
    compat_p.add_argument("--manifest", type=Path, default=default_manifest_path())
    compat_p.add_argument("--projects-dir", type=Path, default=None)
    compat_p.add_argument("--fail-on-regression", action="store_true")
    compat_p.set_defaults(func=cmd_compat)

    py_scaffold_p = sub.add_parser("py-scaffold")
    py_scaffold_p.add_argument("path", type=Path)
    py_scaffold_p.set_defaults(func=cmd_py_scaffold)

    py_build_p = sub.add_parser("py-build")
    py_build_p.add_argument("source", type=Path)
    py_build_p.add_argument("output", type=Path)
    py_build_p.add_argument("--project-attr", type=str, default="project")
    py_build_p.set_defaults(func=cmd_py_build)

    py_export_p = sub.add_parser("py-export")
    py_export_p.add_argument("input", type=Path)
    py_export_p.add_argument("output", type=Path)
    py_export_p.set_defaults(func=cmd_py_export)

    py_run_p = sub.add_parser("py-run")
    py_run_p.add_argument("source", type=Path)
    py_run_p.add_argument("--project-attr", type=str, default="project")
    py_run_p.add_argument("--seconds", type=float, default=1.0)
    py_run_p.add_argument("--dt", type=float, default=1 / 30)
    py_run_p.set_defaults(func=cmd_py_run)

    py_inspect_p = sub.add_parser("py-inspect")
    py_inspect_p.add_argument("source", type=Path)
    py_inspect_p.add_argument("--project-attr", type=str, default="project")
    py_inspect_p.set_defaults(func=cmd_py_inspect)

    return parser


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
        resolved_level = configure_logging(args.log_level, force=True)
        debug(_LOGGER, "cli.main", "configured logging level=%s", resolved_level)
        info(_LOGGER, "cli.main", "dispatching command %s", args.command)
        return args.func(args)
    except (ProjectValidationError, Sb3VmError, RendererError, OSError, CodegenError) as exc:
        error(_LOGGER, "cli.main", "command failed: %s", exc, exc_info=True)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        fatal(_LOGGER, "cli.main", "unexpected fatal failure: %s", exc, exc_info=True)
        raise




if __name__ == "__main__":
    raise SystemExit(main())
