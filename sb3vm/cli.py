from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sb3vm.io.load_sb3 import load_sb3
from sb3vm.io.save_sb3 import save_sb3
from sb3vm.render import MinimalRenderer, RendererError
from sb3vm.vm.compat import default_manifest_path, run_compat_suite
from sb3vm.vm.benchmark import run_benchmark_case
from sb3vm.vm.errors import ProjectValidationError, Sb3VmError
from sb3vm.vm.runtime import Sb3Vm


def cmd_inspect(args: argparse.Namespace) -> int:
    project = load_sb3(args.path)
    vm = Sb3Vm(project)
    print(json.dumps(vm.inspect(), indent=2, sort_keys=True))
    return 0


def cmd_resave(args: argparse.Namespace) -> int:
    project = load_sb3(args.input)
    save_sb3(project, args.output)
    print(f"resaved {args.input} -> {args.output}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    project = load_sb3(args.path)
    vm = Sb3Vm(project)
    vm.run_for(args.seconds, dt=args.dt)
    print(json.dumps(vm.snapshot(), indent=2, sort_keys=True))
    return 0


def cmd_run_display(args: argparse.Namespace) -> int:
    project = load_sb3(args.path)
    vm = Sb3Vm(project)
    renderer = MinimalRenderer(project, vm, scale=args.scale, fps=args.fps)
    renderer.run(seconds=args.seconds, dt=args.dt)
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    project = load_sb3(args.path)
    result = run_benchmark_case(args.name or args.path.stem, project, seconds=args.seconds, dt=args.dt)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


def cmd_compat(args: argparse.Namespace) -> int:
    report = run_compat_suite(
        manifest_path=args.manifest,
        extra_projects_dir=args.projects_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if args.fail_on_regression and report["summary"]["regression_count"] > 0 else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sb3vm.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_p = sub.add_parser("inspect")
    inspect_p.add_argument("path", type=Path)
    inspect_p.set_defaults(func=cmd_inspect)

    resave_p = sub.add_parser("resave")
    resave_p.add_argument("input", type=Path)
    resave_p.add_argument("output", type=Path)
    resave_p.set_defaults(func=cmd_resave)

    run_p = sub.add_parser("run")
    run_p.add_argument("path", type=Path)
    run_p.add_argument("--seconds", type=float, default=1.0)
    run_p.add_argument("--dt", type=float, default=1 / 30)
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

    return parser


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
        return args.func(args)
    except (ProjectValidationError, Sb3VmError, RendererError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
