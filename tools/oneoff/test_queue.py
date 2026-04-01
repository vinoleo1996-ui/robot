import sys
import time
from robot_life.common.schemas import ArbitrationResult, DecisionQueueItem, EventPriority, DecisionMode
from robot_life.event_engine.decision_queue import DecisionQueue

print(f"Testing on Python {sys.version_info.major}.{sys.version_info.minor}")

q = DecisionQueue()
try:
    q.enqueue(
        ArbitrationResult(decision_id="1", trace_id="1", target_behavior="test", priority=EventPriority.P0, mode=DecisionMode.QUEUE, required_resources=[], optional_resources=[], degraded_behavior=None, resume_previous=False, reason="test"),
        timeout_ms=1000
    )
    print("Enqueueing P1 decision...")
    q.enqueue(
        ArbitrationResult(decision_id="2", trace_id="2", target_behavior="test", priority=EventPriority.P1, mode=DecisionMode.QUEUE, required_resources=[], optional_resources=[], degraded_behavior=None, resume_previous=False, reason="test"),
        timeout_ms=1000
    )
    print("Queue size:", len(q))
    
    next_item = q.pop_next()
    print("Popped:", next_item.priority if next_item else None)
    
    print("SUCCESS! No crashes in bisect.insort.")
except Exception as e:
    print(f"CRASH: {e}")
