#!/usr/bin/env python3
"""
Test script to verify P0 bug fixes:
1. debounce_count=1 first event passes
2. Complex payload dedup handling
3. Resource grant/release consistency
4. Priority comparison direction
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))

from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.behavior.resources import ResourceManager
from robot_life.behavior.executor import BehaviorExecutor
from robot_life.common.schemas import (
    DetectionResult,
    RawEvent,
    ArbitrationResult,
    EventPriority,
    DecisionMode,
    new_id,
)
from robot_life.event_engine.builder import EventBuilder
import time


def test_debounce_count_1():
    """Test P0 Fix #3: debounce_count=1 should pass first event"""
    print("\n" + "="*60)
    print("TEST 1: debounce_count=1 first event should PASS")
    print("="*60)
    
    stabilizer = EventStabilizer(debounce_count=1)  # Changed from 2
    builder = EventBuilder()
    
    # First event
    detection = DetectionResult.synthetic(
        detector="test",
        event_type="test_event",
        confidence=0.95,
        payload={"test": "data"}
    )
    raw = builder.build(detection, EventPriority.P2)
    stable = stabilizer.process(raw)
    
    if stable is not None:
        print("✅ PASS: First event passed debounce (count=1)")
        print(f"   Event ID: {stable.stable_event_id[:12]}...")
        print(f"   Stabilized by: {stable.stabilized_by}")
        return True
    else:
        print("❌ FAIL: First event blocked even with count=1")
        return False


def test_complex_payload_dedup():
    """Test P0 Fix #4: dedup should handle complex payloads"""
    print("\n" + "="*60)
    print("TEST 2: Complex payload dedup (nested dict, list, etc.)")
    print("="*60)
    
    stabilizer = EventStabilizer(debounce_count=1)
    builder = EventBuilder()
    
    # Complex payloads that would crash old hash logic
    complex_payloads = [
        {"bbox": [1, 2, 3, 4], "landmarks": [[5.1, 6.2], [7.3, 8.4]]},  # Nested lists
        {"data": {"nested": {"deep": [1, 2, 3]}}},  # Nested dict
        {"array": list(range(100))},  # Large list
        {"mixed": [1, "string", 3.14, {"key": "value"}]},  # Mixed types
    ]
    
    all_passed = True
    for i, payload in enumerate(complex_payloads, 1):
        try:
            detection = DetectionResult.synthetic(
                detector="test",
                event_type="complex_event",
                confidence=0.90,
                payload=payload
            )
            raw = builder.build(detection, EventPriority.P2)
            stable = stabilizer.process(raw)
            
            if stable is not None or i > 1:  # First may be None due to debounce
                print(f"  ✅ Payload {i}: Handled successfully")
                print(f"     Type: {type(payload)}, Keys: {list(payload.keys())}")
            else:
                print(f"  ⚠️  Payload {i}: Returned None (expected for debounce)")
        except Exception as e:
            print(f"  ❌ Payload {i}: CRASHED - {e}")
            all_passed = False
    
    if all_passed:
        print("\n✅ PASS: All complex payloads handled without crashes")
        return True
    else:
        print("\n❌ FAIL: Some payloads caused crashes")
        return False


def test_resource_release():
    """Test P0 Fix #1: grant/release consistency"""
    print("\n" + "="*60)
    print("TEST 3: Resource grant/release consistency")
    print("="*60)
    
    resource_manager = ResourceManager()
    executor = BehaviorExecutor(resource_manager)
    
    # Create a decision that needs resources
    decision = ArbitrationResult(
        decision_id=new_id(),
        trace_id="test-trace",
        target_behavior="test_behavior",
        priority=EventPriority.P2,
        mode=DecisionMode.EXECUTE,
        required_resources=["AudioOut", "HeadMotion"],
        optional_resources=[],
        degraded_behavior=None,
        resume_previous=False,
        reason="test_decision",
    )
    
    # Execute (which grants resources then releases)
    print("1. Executing behavior (grants resources, then releases after execution)...")
    result = executor.execute(decision, duration_ms=1000)
    
    # Check execution result
    if result.status == "finished":
        print(f"   ✓ Execution completed: {result.status}")
    else:
        print(f"   ✗ Execution failed: {result.status}")
        return False
    
    # After execution, verify all resources are free (grant should be released)
    status = resource_manager.get_resource_status()
    
    all_free = all(v == "free" for v in status.values())
    print("\n2. After execution (all resources should be FREE)...")
    for res_name, res_status in status.items():
        symbol = "✓" if res_status == "free" else "✗"
        print(f"   {symbol} {res_name}: {res_status}")
    
    if all_free:
        print("\n✅ PASS: Grant/release consistency is working")
        print("   (Resources were granted during execution, released after)")
        return True
    else:
        print("\n❌ FAIL: Some resources still allocated after execution")
        return False


def test_priority_direction():
    """Test P0 Fix #2: priority comparison direction (P0 > P3)"""
    print("\n" + "="*60)
    print("TEST 4: Priority comparison direction (P0 highest priority)")
    print("="*60)
    
    executor = BehaviorExecutor()
    
    # Test priority conversion
    p0_val = executor._priority_to_int(EventPriority.P0)
    p1_val = executor._priority_to_int(EventPriority.P1)
    p2_val = executor._priority_to_int(EventPriority.P2)
    p3_val = executor._priority_to_int(EventPriority.P3)
    
    print(f"P0 converts to: {p0_val}")
    print(f"P1 converts to: {p1_val}")
    print(f"P2 converts to: {p2_val}")
    print(f"P3 converts to: {p3_val}")
    
    # Verify: P0 > P1 > P2 > P3
    if p0_val > p1_val > p2_val > p3_val:
        print("\n✅ PASS: P0 > P1 > P2 > P3 (correct priority ordering)")
        return True
    else:
        print("\n❌ FAIL: Priority ordering is wrong")
        return False


def main():
    print("\n" + "🔧 "*30)
    print("P0 BUG FIX VERIFICATION TEST SUITE")
    print("🔧 "*30)
    
    results = {
        "debounce_count=1": test_debounce_count_1(),
        "complex_payload_dedup": test_complex_payload_dedup(),
        "resource_release": test_resource_release(),
        "priority_direction": test_priority_direction(),
    }
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(results.values())
    
    print("\n" + "="*60)
    if all_passed:
        print("✅ ALL P0 BUGFIXES VERIFIED SUCCESSFULLY")
    else:
        print(f"❌ {sum(1 for p in results.values() if not p)} TESTS FAILED")
    print("="*60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
