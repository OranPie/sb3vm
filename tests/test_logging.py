from __future__ import annotations

import io

from sb3vm.log import TRACE, configure_logging, debug, error, fatal, get_logger, info, instrument_module, trace, warn


def test_logging_helpers_emit_all_levels_and_source_parts() -> None:
    stream = io.StringIO()
    configure_logging("TRACE", force=True, stream=stream)
    logger = get_logger("sb3vm.tests.logging")

    trace(logger, "test.trace", "trace message")
    debug(logger, "test.debug", "debug message")
    info(logger, "test.info", "info message")
    warn(logger, "test.warn", "warn message")
    error(logger, "test.error", "error message")
    fatal(logger, "test.fatal", "fatal message")

    output = stream.getvalue()
    assert "TRACE sb3vm.tests.logging [test.trace] trace message" in output
    assert "DEBUG sb3vm.tests.logging [test.debug] debug message" in output
    assert "INFO sb3vm.tests.logging [test.info] info message" in output
    assert "WARNING sb3vm.tests.logging [test.warn] warn message" in output
    assert "ERROR sb3vm.tests.logging [test.error] error message" in output
    assert "CRITICAL sb3vm.tests.logging [test.fatal] fatal message" in output


def test_instrument_module_wraps_functions_and_methods_with_trace_logs() -> None:
    stream = io.StringIO()
    configure_logging(TRACE, force=True, stream=stream)
    logger = get_logger("demo.instrumented")

    def sample(value: int) -> int:
        return value + 1

    class Demo:
        def hello(self, name: str) -> str:
            return f"hello {name}"

    sample.__module__ = "demo.instrumented"
    Demo.__module__ = "demo.instrumented"

    namespace = {
        "__name__": "demo.instrumented",
        "sample": sample,
        "Demo": Demo,
    }
    count = instrument_module(namespace, logger)

    assert count >= 2
    assert namespace["sample"](4) == 5
    assert namespace["Demo"]().hello("Ada") == "hello Ada"

    output = stream.getvalue()
    assert "[demo.instrumented.sample] enter(4)" in output
    assert "[demo.instrumented.sample] exit -> 5" in output
    assert "[demo.instrumented.Demo.hello] enter(" in output
    assert "[demo.instrumented.Demo.hello] exit -> 'hello Ada'" in output
