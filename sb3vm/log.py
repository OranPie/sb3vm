from __future__ import annotations

import logging
import os
from typing import IO, Any


TRACE = 5
DEFAULT_LOG_LEVEL = "WARNING"
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _install_trace_level() -> None:
    if logging.getLevelName(TRACE) != "TRACE":
        logging.addLevelName(TRACE, "TRACE")

    if not hasattr(logging.Logger, "trace"):
        def trace(self: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
            if self.isEnabledFor(TRACE):
                self._log(TRACE, msg, args, **kwargs)

        logging.Logger.trace = trace  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    _install_trace_level()
    return logging.getLogger(name)


def parse_log_level(value: str | int | None) -> int:
    _install_trace_level()
    if value is None:
        return logging.getLevelName(DEFAULT_LOG_LEVEL)  # type: ignore[return-value]
    if isinstance(value, int):
        return value
    token = value.strip().upper()
    if token == "TRACE":
        return TRACE
    resolved = logging.getLevelName(token)
    if isinstance(resolved, int):
        return resolved
    raise ValueError(f"Unknown log level: {value}")


def configure_logging(level: str | int | None = None, *, force: bool = False, stream: IO[str] | None = None) -> int:
    resolved = parse_log_level(level if level is not None else os.getenv("SB3VM_LOG_LEVEL", DEFAULT_LOG_LEVEL))
    logging.basicConfig(level=resolved, format=DEFAULT_LOG_FORMAT, force=force, stream=stream)
    return resolved


def _log(logger: logging.Logger, level: int, source_part: str, message: str, *args: Any, **kwargs: Any) -> None:
    logger.log(level, "[%s] " + message, source_part, *args, **kwargs)


def trace(logger: logging.Logger, source_part: str, message: str, *args: Any, **kwargs: Any) -> None:
    _log(logger, TRACE, source_part, message, *args, **kwargs)


def debug(logger: logging.Logger, source_part: str, message: str, *args: Any, **kwargs: Any) -> None:
    _log(logger, logging.DEBUG, source_part, message, *args, **kwargs)


def info(logger: logging.Logger, source_part: str, message: str, *args: Any, **kwargs: Any) -> None:
    _log(logger, logging.INFO, source_part, message, *args, **kwargs)


def warn(logger: logging.Logger, source_part: str, message: str, *args: Any, **kwargs: Any) -> None:
    _log(logger, logging.WARNING, source_part, message, *args, **kwargs)


def error(logger: logging.Logger, source_part: str, message: str, *args: Any, **kwargs: Any) -> None:
    _log(logger, logging.ERROR, source_part, message, *args, **kwargs)


def fatal(logger: logging.Logger, source_part: str, message: str, *args: Any, **kwargs: Any) -> None:
    _log(logger, logging.CRITICAL, source_part, message, *args, **kwargs)


def instrument_module(namespace: dict[str, Any], logger: logging.Logger | None = None) -> int:
    # Deprecated shim kept for compatibility after removing automatic wrapping.
    return 0
