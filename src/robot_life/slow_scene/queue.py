from __future__ import annotations

from dataclasses import dataclass, field
from threading import Condition, Lock
from time import monotonic
from typing import Iterable

from robot_life.common.contracts import priority_rank
from robot_life.common.schemas import EventPriority
from robot_life.slow_scene.schema import SlowSceneRequest


@dataclass(order=True)
class _QueuedItem:
    sort_key: tuple[int, float, int]
    request: SlowSceneRequest = field(compare=False)


class SlowSceneQueue:
    """Bounded in-memory queue with dedup and priority-aware drop policy."""

    def __init__(self, maxsize: int = 16):
        self._maxsize = max(1, maxsize)
        self._items: list[_QueuedItem] = []
        self._sequence = 0
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._closed = False

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def put(self, request: SlowSceneRequest) -> bool:
        """Insert or replace a request without blocking the caller."""
        with self._condition:
            if self._closed:
                return False

            self._remove_by_request_id(request.request_id)
            self._remove_by_dedup_key(request.dedup_key)

            item = self._make_item(request)
            if len(self._items) >= self._maxsize:
                worst = max(self._items, key=lambda queued: queued.sort_key)
                if item.sort_key >= worst.sort_key:
                    return False
                self._items.remove(worst)

            self._items.append(item)
            self._items.sort(key=lambda queued: queued.sort_key)
            self._condition.notify()
            return True

    def get(self, timeout: float | None = None) -> SlowSceneRequest | None:
        with self._condition:
            if timeout is None:
                while not self._items and not self._closed:
                    self._condition.wait()
            else:
                deadline = monotonic() + timeout
                while not self._items and not self._closed:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        return None
                    self._condition.wait(remaining)

            if not self._items:
                return None

            item = self._items.pop(0)
            return item.request

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def purge_expired(self, now: float | None = None) -> list[SlowSceneRequest]:
        now = now if now is not None else monotonic()
        expired: list[SlowSceneRequest] = []
        with self._condition:
            keep: list[_QueuedItem] = []
            for item in self._items:
                if now > item.request.deadline_mono:
                    expired.append(item.request)
                else:
                    keep.append(item)
            self._items = keep
        return expired

    def snapshot(self) -> list[SlowSceneRequest]:
        with self._condition:
            return [item.request for item in self._items]

    def __len__(self) -> int:
        with self._condition:
            return len(self._items)

    def _make_item(self, request: SlowSceneRequest) -> _QueuedItem:
        self._sequence += 1
        return _QueuedItem(
            sort_key=(priority_rank(request.priority), request.submitted_at, self._sequence),
            request=request,
        )

    def _remove_by_request_id(self, request_id: str) -> None:
        self._items = [item for item in self._items if item.request.request_id != request_id]

    def _remove_by_dedup_key(self, dedup_key: str) -> None:
        self._items = [item for item in self._items if item.request.dedup_key != dedup_key]


def choose_latest_request(requests: Iterable[SlowSceneRequest]) -> SlowSceneRequest | None:
    latest: SlowSceneRequest | None = None
    for request in requests:
        if latest is None or request.submitted_at >= latest.submitted_at:
            latest = request
    return latest
