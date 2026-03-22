from __future__ import annotations

import functools
import inspect
import logging
import os
from typing import IO, Any, Callable


TRACE = 5
DEFAULT_LOG_LEVEL = "WARNING"
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_MAX_REPR = 160
_INSTRUMENTED_ATTR = "__sb3vm_instrumented__"


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


def _clip_repr(value: Any) -> str:
    try:
        rendered = repr(value)
    except Exception as exc:  # pragma: no cover - defensive
        rendered = f"<repr failed: {exc}>"
    if len(rendered) > _MAX_REPR:
        return rendered[: _MAX_REPR - 3] + "..."
    return rendered


def _render_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts = [_clip_repr(arg) for arg in args]
    parts.extend(f"{key}={_clip_repr(value)}" for key, value in kwargs.items())
    return ", ".join(parts)


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


def _wrap_callable(logger: logging.Logger, source_part: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(fn, _INSTRUMENTED_ATTR, False):
        return fn

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if logger.isEnabledFor(TRACE):
            trace(logger, source_part, "enter(%s)", _render_call(args, kwargs))
        try:
            result = fn(*args, **kwargs)
        except Exception:
            error(logger, source_part, "exception raised", exc_info=True)
            raise
        if logger.isEnabledFor(TRACE):
            trace(logger, source_part, "exit -> %s", _clip_repr(result))
        return result

    setattr(wrapper, _INSTRUMENTED_ATTR, True)
    return wrapper


def _wrap_class(logger: logging.Logger, module_name: str, class_name: str, cls: type[Any]) -> int:
    count = 0
    for attr_name, attr_value in list(vars(cls).items()):
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        source_part = f"{module_name}.{class_name}.{attr_name}"
        if isinstance(attr_value, staticmethod):
            wrapped = _wrap_callable(logger, source_part, attr_value.__func__)
            setattr(cls, attr_name, staticmethod(wrapped))
            count += 1
            continue
        if isinstance(attr_value, classmethod):
            wrapped = _wrap_callable(logger, source_part, attr_value.__func__)
            setattr(cls, attr_name, classmethod(wrapped))
            count += 1
            continue
        if inspect.isfunction(attr_value):
            setattr(cls, attr_name, _wrap_callable(logger, source_part, attr_value))
            count += 1
    return count


def instrument_module(namespace: dict[str, Any], logger: logging.Logger | None = None) -> int:
    module_name = str(namespace.get("__name__", "sb3vm.unknown"))
    logger = logger or get_logger(module_name)
    count = 0
    for name, value in list(namespace.items()):
        if inspect.isfunction(value) and getattr(value, "__module__", None) == module_name:
            namespace[name] = _wrap_callable(logger, f"{module_name}.{name}", value)
            count += 1
            continue
        if inspect.isclass(value) and getattr(value, "__module__", None) == module_name:
            count += _wrap_class(logger, module_name, value.__name__, value)
    debug(logger, f"{module_name}.instrument", "instrumented %d callables", count)
    return count
