"""Stdlib logging setup and tool-instrumentation decorator for rs-mcp-server."""
import functools
import inspect
import logging
import sys
import time

_TOOL_LOGGER = logging.getLogger("rs_mcp_server.tools")
_MAX_ARG_VALUE = 200
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, stream=sys.stderr)
    logging.getLogger("rs_mcp_server").setLevel(logging.INFO)


def _escape(s: str) -> str:
    return s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _format_args(bound: dict) -> str:
    parts = []
    for k, v in bound.items():
        s = _escape(str(v))
        if len(s) > _MAX_ARG_VALUE:
            s = s[:_MAX_ARG_VALUE] + "…"
        parts.append(f"{k}='{s}'")
    return " ".join(parts)


def instrument(tool_name: str):
    def decorator(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                args_str = _format_args(sig.bind(*args, **kwargs).arguments)
            except TypeError:
                args_str = ""
            t0 = time.monotonic()
            _TOOL_LOGGER.info(f"tool_call_start tool={tool_name} {args_str}")
            try:
                result = await fn(*args, **kwargs)
            except Exception as e:
                dt = int((time.monotonic() - t0) * 1000)
                _TOOL_LOGGER.exception(
                    f"tool_call_error tool={tool_name} {args_str} "
                    f"error_type={type(e).__name__} error_msg={str(e)[:200]} duration_ms={dt}"
                )
                raise
            dt = int((time.monotonic() - t0) * 1000)
            result_len = len(result) if hasattr(result, "__len__") else -1
            _TOOL_LOGGER.info(
                f"tool_call_end tool={tool_name} duration_ms={dt} result_len={result_len}"
            )
            return result

        return wrapper

    return decorator
