"""Stdlib logging setup and tool-instrumentation decorator for rs-mcp-server."""
import functools
import inspect
import logging
import re
import sys
import time

_TOOL_LOGGER = logging.getLogger("rs_mcp_server.tools")
_MAX_ARG_VALUE = 200
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

_RESET = "\033[0m"
_TOOL_COLOR = 39        # bright sky-blue — applied to tool name regardless of level
_ERROR_TYPE_COLOR = 165  # magenta — applied to error_type value regardless of level
_LEVEL_COLORS: dict[str, tuple[int, int, int]] = {
    # (label, source module, method) — INFO intentionally absent (uncolored)
    "WARNING":  (100, 178, 220),  # yellow: olive, amber, gold
    "ERROR":    (88, 124, 160),   # red: dark, medium, light
    "CRITICAL": (52, 88, 124),    # dark-red (FATAL)
}
_TOOL_RE = re.compile(r"^(tool_call_(?:start|end|error)\s+tool=)(\w+)")
# Lookahead on \s+error_msg= rejects user-injected error_type= occurrences inside quoted args (which end with ').
_ERROR_TYPE_RE = re.compile(r"(?<=error_type=)(\w+)(?=\s+error_msg=)")
_METHOD_RE = re.compile(r"^(\w+)")


def _wrap(s: str, code: int) -> str:
    return f"\033[38;5;{code}m{s}{_RESET}"


class _ColorFormatter(logging.Formatter):
    def formatMessage(self, record: logging.LogRecord) -> str:
        orig_level = record.levelname
        orig_name = record.name
        orig_message = record.message
        try:
            record.message = _TOOL_RE.sub(
                lambda m: m.group(1) + _wrap(m.group(2), _TOOL_COLOR),
                orig_message,
                count=1,
            )
            record.message = _ERROR_TYPE_RE.sub(
                lambda m: _wrap(m.group(0), _ERROR_TYPE_COLOR),
                record.message,
            )
            colors = _LEVEL_COLORS.get(record.levelname)
            if colors is not None:
                label_c, name_c, method_c = colors
                record.levelname = _wrap(orig_level, label_c)
                record.name = _wrap(orig_name, name_c)
                record.message = _METHOD_RE.sub(
                    lambda m: _wrap(m.group(1), method_c),
                    record.message,
                    count=1,
                )
            return super().formatMessage(record)
        finally:
            record.levelname = orig_level
            record.name = orig_name
            record.message = orig_message


def setup_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_rs_mcp_color", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_ColorFormatter(_LOG_FORMAT))
    handler._rs_mcp_color = True
    root.addHandler(handler)
    root.setLevel(logging.INFO)
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
