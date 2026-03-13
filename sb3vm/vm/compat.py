from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sb3vm.io.load_sb3 import load_sb3
from sb3vm.vm.errors import ProjectValidationError
from sb3vm.vm.input_provider import HeadlessInputProvider
from sb3vm.vm.runtime import Sb3Vm


FULLY_SUPPORTED = "fully_supported"
PARTIALLY_SUPPORTED = "partially_supported"
PARSED_ONLY = "parsed_only"
UNSUPPORTED = "unsupported"
LABELS = (FULLY_SUPPORTED, PARTIALLY_SUPPORTED, PARSED_ONLY, UNSUPPORTED)


@dataclass(frozen=True)
class RuntimeConfig:
    seconds: float | None = None
    steps: int | None = None
    dt: float = 1 / 30
    random_seed: int | None = None
    enable_compilation: bool = False
    pressed_keys: tuple[str, ...] = ()
    mouse_x: float = 0.0
    mouse_y: float = 0.0
    mouse_down: bool = False
    answers: tuple[str, ...] = ()
    answer: str = ""
    timer_override: float | None = None


@dataclass(frozen=True)
class CheckpointSpec:
    name: str
    after_steps: int
    snapshot_path: Path


@dataclass(frozen=True)
class FixtureSpec:
    fixture_id: str
    kind: str
    path: Path
    enabled: bool = True
    execute: bool = True
    runtime: RuntimeConfig = RuntimeConfig()
    final_snapshot_path: Path | None = None
    checkpoints: tuple[CheckpointSpec, ...] = ()
    expected_label: str | None = None
    label_override: str | None = None
    label_override_reason: str | None = None
    source: str = "manifest"


@dataclass
class FixtureRunResult:
    fixture_id: str
    kind: str
    path: str
    source: str
    status: str
    label: str
    computed_label: str
    expected_label: str | None
    execute: bool
    regressions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    inspect: dict[str, Any] | None = None
    final_snapshot: dict[str, Any] | None = None
    checkpoint_results: list[dict[str, Any]] = field(default_factory=list)
    label_override_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "kind": self.kind,
            "path": self.path,
            "source": self.source,
            "status": self.status,
            "label": self.label,
            "computed_label": self.computed_label,
            "expected_label": self.expected_label,
            "execute": self.execute,
            "errors": list(self.errors),
            "regressions": list(self.regressions),
            "inspect": self.inspect,
            "final_snapshot": self.final_snapshot,
            "checkpoint_results": list(self.checkpoint_results),
            "label_override_reason": self.label_override_reason,
        }


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "compat" / "manifest.json"


def run_compat_suite(
    *,
    manifest_path: str | Path | None = None,
    extra_projects_dir: str | Path | None = None,
) -> dict[str, Any]:
    manifest = Path(manifest_path) if manifest_path is not None else default_manifest_path()
    fixtures = load_manifest(manifest)
    fixtures.extend(load_extra_projects(extra_projects_dir) if extra_projects_dir is not None else [])

    results = [run_fixture(spec) for spec in fixtures if spec.enabled]
    opcode_matrix = build_opcode_matrix(results)
    label_counts = {label: sum(1 for result in results if result.label == label) for label in LABELS}
    regressions = [
        {
            "fixture_id": result.fixture_id,
            "path": result.path,
            "messages": list(result.regressions),
        }
        for result in results
        if result.regressions
    ]
    return {
        "summary": {
            "fixture_count": len(results),
            "label_counts": label_counts,
            "regression_count": len(regressions),
        },
        "projects": [result.to_dict() for result in results],
        "opcode_matrix": opcode_matrix,
        "regressions": regressions,
    }


def load_manifest(path: str | Path) -> list[FixtureSpec]:
    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("fixtures"), list):
        raise ProjectValidationError("Compatibility manifest must contain a fixtures list", reference=str(manifest_path))

    fixtures: list[FixtureSpec] = []
    for raw in data["fixtures"]:
        if not isinstance(raw, dict):
            raise ProjectValidationError("Compatibility fixture entries must be objects", reference=str(manifest_path))
        fixture_id = str(raw["id"])
        runtime_raw = raw.get("runtime", {})
        if not isinstance(runtime_raw, dict):
            raise ProjectValidationError("Compatibility fixture runtime must be an object", reference=fixture_id)
        runtime = RuntimeConfig(
            seconds=runtime_raw.get("seconds"),
            steps=runtime_raw.get("steps"),
            dt=float(runtime_raw.get("dt", 1 / 30)),
            random_seed=runtime_raw.get("random_seed"),
            enable_compilation=bool(runtime_raw.get("enable_compilation", False)),
            pressed_keys=tuple(str(item) for item in runtime_raw.get("pressed_keys", [])),
            mouse_x=float(runtime_raw.get("mouse_x", 0.0)),
            mouse_y=float(runtime_raw.get("mouse_y", 0.0)),
            mouse_down=bool(runtime_raw.get("mouse_down", False)),
            answers=tuple(str(item) for item in runtime_raw.get("answers", [])),
            answer=str(runtime_raw.get("answer", "")),
            timer_override=runtime_raw.get("timer_override"),
        )

        expect_raw = raw.get("expect", {})
        if not isinstance(expect_raw, dict):
            raise ProjectValidationError("Compatibility fixture expect must be an object", reference=fixture_id)
        checkpoints_raw = expect_raw.get("checkpoints", [])
        checkpoints: list[CheckpointSpec] = []
        for item in checkpoints_raw:
            checkpoints.append(
                CheckpointSpec(
                    name=str(item["name"]),
                    after_steps=int(item["after_steps"]),
                    snapshot_path=(manifest_path.parent / str(item["snapshot"])).resolve(),
                )
            )

        override_raw = raw.get("label_override")
        override_label: str | None = None
        override_reason: str | None = None
        if override_raw is not None:
            if not isinstance(override_raw, dict) or "label" not in override_raw:
                raise ProjectValidationError("label_override must include label", reference=fixture_id)
            override_label = str(override_raw["label"])
            override_reason = str(override_raw.get("reason", "")) or None

        fixtures.append(
            FixtureSpec(
                fixture_id=fixture_id,
                kind=str(raw.get("kind", "real_project")),
                path=(manifest_path.parent / str(raw["path"])).resolve(),
                enabled=bool(raw.get("enabled", True)),
                execute=bool(raw.get("execute", True)),
                runtime=runtime,
                final_snapshot_path=(manifest_path.parent / str(expect_raw["final_snapshot"])).resolve()
                if "final_snapshot" in expect_raw
                else None,
                checkpoints=tuple(checkpoints),
                expected_label=str(raw["expected_label"]) if raw.get("expected_label") is not None else None,
                label_override=override_label,
                label_override_reason=override_reason,
            )
        )
    return fixtures


def load_extra_projects(path: str | Path) -> list[FixtureSpec]:
    root = Path(path)
    fixtures: list[FixtureSpec] = []
    for project_path in sorted(root.glob("*.sb3")):
        fixtures.append(
            FixtureSpec(
                fixture_id=f"extra:{project_path.stem}",
                kind="real_project",
                path=project_path.resolve(),
                execute=False,
                expected_label=PARSED_ONLY,
                source="extra_projects_dir",
            )
        )
    return fixtures


def run_fixture(spec: FixtureSpec) -> FixtureRunResult:
    result = FixtureRunResult(
        fixture_id=spec.fixture_id,
        kind=spec.kind,
        path=str(spec.path),
        source=spec.source,
        status="ok",
        label=PARSED_ONLY,
        computed_label=PARSED_ONLY,
        expected_label=spec.expected_label,
        execute=spec.execute,
        label_override_reason=spec.label_override_reason,
    )
    try:
        project = load_sb3(spec.path)
    except (FileNotFoundError, ProjectValidationError, OSError) as exc:
        result.status = "load_error"
        result.errors.append(str(exc))
        result.computed_label = UNSUPPORTED
        result.label = spec.label_override or UNSUPPORTED
        _apply_expected_label_regression(spec, result)
        return result

    vm = Sb3Vm(
        project,
        enable_compilation=spec.runtime.enable_compilation,
        random_seed=spec.runtime.random_seed,
        input_provider=HeadlessInputProvider(
            pressed_keys=set(spec.runtime.pressed_keys),
            mouse_x_value=spec.runtime.mouse_x,
            mouse_y_value=spec.runtime.mouse_y,
            mouse_down_value=spec.runtime.mouse_down,
            answers=list(spec.runtime.answers),
            answer_value=spec.runtime.answer,
            timer_override_value=spec.runtime.timer_override,
        ),
    )
    result.inspect = vm.inspect()

    if spec.execute:
        final_snapshot, checkpoint_results = _run_with_expectations(vm, spec)
        result.final_snapshot = final_snapshot
        result.checkpoint_results = checkpoint_results
        if spec.final_snapshot_path is not None:
            expected_final = _load_json(spec.final_snapshot_path)
            mismatches = compare_subset(expected_final, final_snapshot, path="final_snapshot")
            result.regressions.extend(mismatches)
        for checkpoint_result in checkpoint_results:
            result.regressions.extend(checkpoint_result["mismatches"])

    computed_label = derive_label(spec, result)
    result.computed_label = computed_label
    result.label = spec.label_override or computed_label
    _apply_expected_label_regression(spec, result)
    return result


def _run_with_expectations(vm: Sb3Vm, spec: FixtureSpec) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    checkpoint_results: list[dict[str, Any]] = []
    if spec.checkpoints or spec.runtime.steps is not None:
        vm.start_green_flag()
        current_steps = 0
        expected_steps = max([checkpoint.after_steps for checkpoint in spec.checkpoints], default=0)
        if spec.runtime.steps is not None:
            expected_steps = max(expected_steps, spec.runtime.steps)
        checkpoints_by_step: dict[int, list[CheckpointSpec]] = {}
        for checkpoint in spec.checkpoints:
            checkpoints_by_step.setdefault(checkpoint.after_steps, []).append(checkpoint)

        for _ in range(expected_steps):
            vm.step(spec.runtime.dt)
            current_steps += 1
            for checkpoint in checkpoints_by_step.get(current_steps, []):
                actual = vm.snapshot()
                expected = _load_json(checkpoint.snapshot_path)
                checkpoint_results.append(
                    {
                        "name": checkpoint.name,
                        "after_steps": checkpoint.after_steps,
                        "snapshot": actual,
                        "mismatches": compare_subset(expected, actual, path=f"checkpoint:{checkpoint.name}"),
                    }
                )
        return vm.snapshot(), checkpoint_results

    seconds = spec.runtime.seconds if spec.runtime.seconds is not None else 1.0
    vm.run_for(seconds, dt=spec.runtime.dt)
    return vm.snapshot(), checkpoint_results


def derive_label(spec: FixtureSpec, result: FixtureRunResult) -> str:
    if result.status != "ok":
        return UNSUPPORTED
    if not spec.execute:
        return PARSED_ONLY
    if result.regressions:
        return PARTIALLY_SUPPORTED
    inspect = result.inspect or {}
    unsupported = inspect.get("unsupported_scripts", [])
    final_snapshot = result.final_snapshot or {}
    runtime_diagnostics = final_snapshot.get("runtime_diagnostics", [])
    if unsupported or runtime_diagnostics:
        return PARTIALLY_SUPPORTED
    return FULLY_SUPPORTED


def build_opcode_matrix(results: list[FixtureRunResult]) -> dict[str, Any]:
    matrix: dict[str, dict[str, Any]] = {}
    for result in results:
        inspect = result.inspect or {}
        coverage = inspect.get("opcode_coverage", {})
        by_opcode = coverage.get("by_opcode", {})
        supported = coverage.get("supported_by_opcode", {})
        unsupported = coverage.get("unsupported_by_opcode", {})
        executed_passing = result.execute and not result.regressions and result.status == "ok"
        for opcode, count in by_opcode.items():
            entry = matrix.setdefault(
                opcode,
                {
                    "seen_count": 0,
                    "seen_in_fixtures": 0,
                    "parse_supported_count": 0,
                    "parse_unsupported_count": 0,
                    "executed_passing_count": 0,
                },
            )
            entry["seen_count"] += int(count)
            entry["seen_in_fixtures"] += 1
            entry["parse_supported_count"] += int(supported.get(opcode, 0))
            entry["parse_unsupported_count"] += int(unsupported.get(opcode, 0))
            if executed_passing:
                entry["executed_passing_count"] += int(count)
    return {opcode: matrix[opcode] for opcode in sorted(matrix)}


def compare_subset(expected: Any, actual: Any, *, path: str) -> list[str]:
    mismatches: list[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        for key, value in expected.items():
            if key not in actual:
                mismatches.append(f"{path}.{key}: missing key")
                continue
            mismatches.extend(compare_subset(value, actual[key], path=f"{path}.{key}"))
        return mismatches
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected list, got {type(actual).__name__}"]
        if len(expected) != len(actual):
            mismatches.append(f"{path}: expected list length {len(expected)}, got {len(actual)}")
            return mismatches
        for index, value in enumerate(expected):
            mismatches.extend(compare_subset(value, actual[index], path=f"{path}[{index}]"))
        return mismatches
    if expected != actual:
        mismatches.append(f"{path}: expected {expected!r}, got {actual!r}")
    return mismatches


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _apply_expected_label_regression(spec: FixtureSpec, result: FixtureRunResult) -> None:
    if spec.expected_label is not None and result.label != spec.expected_label:
        result.regressions.append(
            f"label: expected {spec.expected_label!r}, got {result.label!r}"
        )
