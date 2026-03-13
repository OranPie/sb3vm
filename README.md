# sb3vm MVP

Headless Scratch `.sb3` VM in Python.

Included:
- `.sb3` load/save roundtrip
- project data preservation for known fields and raw JSON passthrough
- normalized event-script extraction
- core interpreter for events, control, data, operators, and state-only motion/looks
- optional minimal renderer for stage/sprite visualization
- CLI commands: `inspect`, `resave`, `run`, `run-display`, `benchmark`, `compat`
- basic pytest coverage

Not included:
- sound
- perfect visual fidelity
- full collision accuracy
- advanced effects

Display mode:
- install optional renderer deps with `pip install 'sb3vm[render]'`
- run a project with a window via `python -m sb3vm.cli run-display examples/demo.sb3`
- SVG costumes require the optional `cairosvg` dependency from the render extra

Benchmarking:
- compare interpreted vs compiled execution with `python -m sb3vm.cli benchmark examples/benchmark_hot_loop.sb3 --seconds 0.2`
- additional benchmark fixtures live in `examples/benchmark_hot_loop.sb3` and `examples/benchmark_broadcast_fanout.sb3`

Compatibility lab:
- run the checked-in compatibility corpus with `python -m sb3vm.cli compat`
- add ad hoc local projects with `python -m sb3vm.cli compat --projects-dir /path/to/sb3s`
- fail CI on compatibility regressions with `python -m sb3vm.cli compat --fail-on-regression`
