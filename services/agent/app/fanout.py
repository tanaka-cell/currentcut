"""Run the same call over many items at once, in a fixed number of lanes.

Every expensive step in the run is one API call per thing — per clip, per
segment, per claim — and the calls do not depend on each other. Done one after
another, a night's rushes turns into a queue: three hours of footage is
hundreds of segments, and at a second or two each the wait stops being a
night's work and becomes a day's.

The lanes are bounded on purpose. The limit is the provider's rate limit, not
the machine, so "as many as there are items" is the one setting guaranteed to
fail on real input.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

from . import config

T = TypeVar("T")
R = TypeVar("R")


def fan_out(items: Iterable[T], fn: Callable[[T], R], *,
            workers: int | None = None,
            on_result: Callable[[T, R], None] | None = None) -> list[R]:
    """Apply `fn` to every item concurrently; return results in input order.

    `on_result` fires as each item lands, in completion order — that is what
    progress lines want, so a director watching sees things finishing rather
    than an ordered list that appears all at once at the end.

    Failure behaves as it would in a plain loop: the first exception is raised
    once the work in flight has finished, so one bad clip does not leave the
    rest half-done and unrecorded.
    """
    items = list(items)
    if not items:
        return []
    lanes = max(1, min(workers or config.MAX_CONCURRENCY, len(items)))
    if lanes == 1:
        out = []
        for item in items:
            result = fn(item)
            if on_result:
                on_result(item, result)
            out.append(result)
        return out

    results: list[R] = [None] * len(items)  # type: ignore[list-item]
    errors: list[tuple[int, BaseException]] = []
    with ThreadPoolExecutor(max_workers=lanes) as pool:
        futures = {pool.submit(fn, item): (i, item) for i, item in enumerate(items)}
        for future in as_completed(futures):
            i, item = futures[future]
            try:
                results[i] = future.result()
            except BaseException as exc:  # noqa: BLE001 — re-raised below
                errors.append((i, exc))
                continue
            if on_result:
                on_result(item, results[i])
    if errors:
        raise min(errors, key=lambda e: e[0])[1]
    return results
