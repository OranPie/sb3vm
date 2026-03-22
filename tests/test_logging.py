from __future__ import annotations

import io

from sb3vm.log import TRACE, configure_logging, debug, error, fatal, get_logger, info, trace, warn


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
def test_trace_level_configures_and_logs_manually() -> None:
    stream = io.StringIO()
    resolved = configure_logging(TRACE, force=True, stream=stream)
    logger = get_logger("demo.manual")

    trace(logger, "demo.manual.run", "manual trace %s", 1)
    debug(logger, "demo.manual.run", "manual debug %s", 2)

    output = stream.getvalue()
    assert resolved == TRACE
    assert "TRACE demo.manual [demo.manual.run] manual trace 1" in output
    assert "DEBUG demo.manual [demo.manual.run] manual debug 2" in output
