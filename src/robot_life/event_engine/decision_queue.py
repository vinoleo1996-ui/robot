from __future__ import annotations

from typing import Any

from robot_life.common.schemas import ArbitrationResult, DecisionQueueItem, EventPriority, new_id, now_mono


PRIORITY_ORDER = {
    EventPriority.P0: 0,
    EventPriority.P1: 1,
    EventPriority.P2: 2,
    EventPriority.P3: 3,
}


class DecisionQueue:
    """Priority-aware queue for deferred decisions."""

    def __init__(self, default_timeout_ms: int = 5_000, max_size: int = 32):
        self._default_timeout_ms = default_timeout_ms
        self._max_size = max_size
        self._items: list[DecisionQueueItem] = []
        self._metadata: dict[str, dict[str, Any]] = {}
        self._recent_replace_touched: dict[str, float] = {}

    def enqueue(
        self,
        decision: ArbitrationResult,
        timeout_ms: int | None = None,
        *,
        replace_key: str | None = None,
        debounce_window_ms: int = 0,
    ) -> DecisionQueueItem | None:
        """Add a decision to the queue, optionally replacing an equivalent queued item."""
        now = now_mono()
        timeout = timeout_ms if timeout_ms is not None else self._default_timeout_ms
        self.prune_expired(now)
        self._prune_recent_replace_keys(now, debounce_window_ms=debounce_window_ms)

        if replace_key is not None:
            existing = self._find_by_replace_key(replace_key)
            recent_touch = self._recent_replace_touched.get(replace_key)
            if debounce_window_ms > 0 and recent_touch is not None:
                debounce_window_s = debounce_window_ms / 1000
                if (now - recent_touch) < debounce_window_s:
                    if existing is not None:
                        item = DecisionQueueItem(
                            queue_id=existing.queue_id,
                            enqueued_at_monotonic=existing.enqueued_at_monotonic,
                            valid_until_monotonic=now + (timeout / 1000),
                            decision=decision,
                        )
                        self._replace_item(item, replace_key=replace_key, touched_at=now)
                        self._recent_replace_touched[replace_key] = now
                        return item
                    return None

            if existing is not None:
                item = DecisionQueueItem(
                    queue_id=existing.queue_id,
                    enqueued_at_monotonic=existing.enqueued_at_monotonic,
                    valid_until_monotonic=now + (timeout / 1000),
                    decision=decision,
                )
                self._replace_item(item, replace_key=replace_key, touched_at=now)
                self._recent_replace_touched[replace_key] = now
                return item

        item = DecisionQueueItem(
            queue_id=new_id(),
            enqueued_at_monotonic=now,
            valid_until_monotonic=now + (timeout / 1000),
            decision=decision,
        )

        self._items.append(item)
        self._metadata[item.queue_id] = {
            "replace_key": replace_key,
            "touched_at_monotonic": now,
        }
        if replace_key is not None:
            self._recent_replace_touched[replace_key] = now
        self._items.sort(key=self._sort_key)

        if len(self._items) > self._max_size:
            dropped = self._items.pop()
            self._metadata.pop(dropped.queue_id, None)
            if dropped.queue_id == item.queue_id:
                return None

        return item

    def pop_next(self) -> ArbitrationResult | None:
        """Pop the highest-priority non-expired decision."""
        self.prune_expired()
        if not self._items:
            return None
        item = self._pop_item_at_index(0)
        return item.decision

    def pop_starved_oldest(
        self,
        *,
        starvation_after_ms: int,
        priorities: set[EventPriority] | None = None,
        now: float | None = None,
    ) -> ArbitrationResult | None:
        self.prune_expired(now)
        if not self._items or starvation_after_ms <= 0:
            return None

        current = now if now is not None else now_mono()
        threshold_s = starvation_after_ms / 1000
        eligible: list[tuple[int, DecisionQueueItem]] = []
        for index, item in enumerate(self._items):
            if priorities is not None and item.decision.priority not in priorities:
                continue
            if (current - item.enqueued_at_monotonic) < threshold_s:
                continue
            eligible.append((index, item))

        if not eligible:
            return None

        eligible.sort(key=lambda pair: pair[1].enqueued_at_monotonic)
        item = self._pop_item_at_index(eligible[0][0])
        return item.decision

    def drop_oldest(self, priority: EventPriority | None = None) -> DecisionQueueItem | None:
        """Remove and return the oldest item, optionally restricted to a priority."""
        self.prune_expired()
        if not self._items:
            return None

        if priority is None:
            return self._pop_item_at_index(0)

        for index, item in enumerate(self._items):
            if item.decision.priority == priority:
                return self._pop_item_at_index(index)
        return None

    def prune_expired(self, now: float | None = None) -> None:
        current = now if now is not None else now_mono()
        active_items: list[DecisionQueueItem] = []
        for item in self._items:
            if item.valid_until_monotonic > current:
                active_items.append(item)
                continue
            self._metadata.pop(item.queue_id, None)
        self._items = active_items

    def __len__(self) -> int:
        self.prune_expired()
        return len(self._items)

    def count(self, priority: EventPriority | None = None) -> int:
        self.prune_expired()
        if priority is None:
            return len(self._items)
        return sum(1 for item in self._items if item.decision.priority == priority)

    def has_replace_key(self, replace_key: str) -> bool:
        self.prune_expired()
        return self._find_by_replace_key(replace_key) is not None

    def items(self, priority: EventPriority | None = None) -> list[DecisionQueueItem]:
        self.prune_expired()
        if priority is None:
            return list(self._items)
        return [item for item in self._items if item.decision.priority == priority]

    def replace_key_for(self, item: DecisionQueueItem) -> str | None:
        metadata = self._metadata.get(item.queue_id)
        if metadata is None:
            return None
        replace_key = metadata.get("replace_key")
        return str(replace_key) if replace_key is not None else None

    def drop_queue_id(self, queue_id: str) -> DecisionQueueItem | None:
        self.prune_expired()
        for index, item in enumerate(self._items):
            if item.queue_id != queue_id:
                continue
            return self._pop_item_at_index(index)
        return None

    def clear(self) -> None:
        self._items.clear()
        self._metadata.clear()
        self._recent_replace_touched.clear()

    @staticmethod
    def _sort_key(item: DecisionQueueItem) -> tuple[int, float]:
        return (
            PRIORITY_ORDER.get(item.decision.priority, 99),
            item.enqueued_at_monotonic,
        )

    def _find_by_replace_key(self, replace_key: str) -> DecisionQueueItem | None:
        for item in self._items:
            metadata = self._metadata.get(item.queue_id)
            if metadata is not None and metadata.get("replace_key") == replace_key:
                return item
        return None

    def _replace_item(self, item: DecisionQueueItem, *, replace_key: str, touched_at: float) -> None:
        for index, current in enumerate(self._items):
            if current.queue_id != item.queue_id:
                continue
            self._items[index] = item
            self._metadata[item.queue_id] = {
                "replace_key": replace_key,
                "touched_at_monotonic": touched_at,
            }
            self._items.sort(key=self._sort_key)
            return

    def _pop_item_at_index(self, index: int) -> DecisionQueueItem:
        item = self._items.pop(index)
        self._metadata.pop(item.queue_id, None)
        return item

    def _prune_recent_replace_keys(self, now: float, *, debounce_window_ms: int) -> None:
        if debounce_window_ms <= 0:
            return
        debounce_window_s = debounce_window_ms / 1000
        stale_keys = [
            key
            for key, touched_at in self._recent_replace_touched.items()
            if (now - touched_at) >= debounce_window_s
        ]
        for key in stale_keys:
            self._recent_replace_touched.pop(key, None)
