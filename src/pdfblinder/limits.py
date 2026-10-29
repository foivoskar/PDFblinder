"""Per-job limits. OS sandboxing remains a deployment concern."""

import math
from dataclasses import asdict, dataclass


class LimitError(RuntimeError):
    """A job exceeded a configured limit."""


@dataclass(frozen=True)
class Limits:
    max_input_bytes: int = 100 * 1024 * 1024
    max_work_bytes: int = 512 * 1024 * 1024
    max_memory_bytes: int = 1536 * 1024 * 1024
    max_pages: int = 200
    max_objects: int = 100_000
    max_page_objects: int = 20_000
    max_depth: int = 32
    max_page_pixels: int = 25_000_000
    max_total_pixels: int = 250_000_000

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")


def validate_timeout(timeout):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be finite and positive.")


def linux_hard_limits(limits, timeout):
    """Supplement portable sampling with inherited Linux kernel limits."""
    import sys

    if sys.platform != "linux":
        return
    import resource

    for kind, value in (
        (resource.RLIMIT_AS, limits.max_memory_bytes),
        (resource.RLIMIT_FSIZE, limits.max_work_bytes),
        (resource.RLIMIT_CPU, max(1, math.ceil(timeout))),
        (resource.RLIMIT_CORE, 0),
    ):
        _, hard = resource.getrlimit(kind)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(kind, (value, value))
