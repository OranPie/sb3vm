from __future__ import annotations

import time
from dataclasses import dataclass

from sb3vm.model.project import Project
from sb3vm.vm.runtime import Sb3Vm


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    iterations: int
    interpreted_seconds: float
    compiled_seconds: float

    def to_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "interpreted_seconds": self.interpreted_seconds,
            "compiled_seconds": self.compiled_seconds,
        }


def _run_engine(project: Project, *, enable_compilation: bool, seconds: float, dt: float, iterations: int) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        vm = Sb3Vm(project, enable_compilation=enable_compilation)
        vm.run_for(seconds, dt=dt)
    return time.perf_counter() - start


def _calibrate_iterations(project: Project, *, seconds: float, dt: float, min_wall_time: float) -> int:
    iterations = 1
    while iterations < 4096:
        elapsed = _run_engine(project, enable_compilation=False, seconds=seconds, dt=dt, iterations=iterations)
        if elapsed >= min_wall_time:
            return iterations
        iterations *= 2
    return iterations


def run_benchmark_case(
    name: str,
    project: Project,
    *,
    seconds: float,
    dt: float = 1 / 30,
    min_wall_time: float = 0.05,
) -> BenchmarkResult:
    iterations = _calibrate_iterations(project, seconds=seconds, dt=dt, min_wall_time=min_wall_time)
    interpreted_seconds = _run_engine(project, enable_compilation=False, seconds=seconds, dt=dt, iterations=iterations)
    compiled_seconds = _run_engine(project, enable_compilation=True, seconds=seconds, dt=dt, iterations=iterations)

    return BenchmarkResult(
        name=name,
        iterations=iterations,
        interpreted_seconds=interpreted_seconds,
        compiled_seconds=compiled_seconds,
    )
    start = time.perf_counter()
    interpreted.run_for(seconds, dt=dt)
    interpreted_seconds = time.perf_counter() - start

    start = time.perf_counter()
    compiled.run_for(seconds, dt=dt)
    compiled_seconds = time.perf_counter() - start

    return BenchmarkResult(
        name=name,
        interpreted_seconds=interpreted_seconds,
        compiled_seconds=compiled_seconds,
    )
