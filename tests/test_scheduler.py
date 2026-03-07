"""Tests for GathererScheduler."""
import sys
import time
import unittest
from unittest.mock import patch
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.scheduler import GathererScheduler


def _make_counter(name):
    """Return a gatherer function and a call-count list for inspection."""
    calls = []
    def fn():
        calls.append(time.time())
        return {name: len(calls)}
    return fn, calls


class TestGathererSchedulerInit(unittest.TestCase):

    def test_not_ready_before_first_tick(self):
        fn, _ = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {}, 60)
        self.assertFalse(s.ready)

    def test_ready_after_first_tick(self):
        fn, _ = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {}, 60)
        _, _, _ = s.tick()
        self.assertTrue(s.ready)

    def test_default_interval_floored_to_min(self):
        fn, _ = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {}, 1)  # below MIN_INTERVAL
        # effective interval should be MIN_INTERVAL (5)
        self.assertEqual(s._interval_for("cpu"), GathererScheduler.MIN_INTERVAL)

    def test_base_tick_stored(self):
        fn, _ = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {}, 60, base_tick=3)
        self.assertEqual(s.base_tick, 3)

    def test_base_tick_floored_to_min(self):
        fn, _ = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {}, 60, base_tick=0)
        self.assertEqual(s.base_tick, GathererScheduler.MIN_BASE_TICK)

    def test_empty_gatherers_ready(self):
        s = GathererScheduler({}, {}, 60)
        self.assertTrue(s.ready)


class TestGathererSchedulerTick(unittest.TestCase):

    def test_all_gatherers_run_on_first_tick(self):
        cpu_fn, cpu_calls = _make_counter("cpu")
        mem_fn, mem_calls = _make_counter("memory")
        s = GathererScheduler({"cpu": cpu_fn, "memory": mem_fn}, {}, 60)
        cache, timings, _ = s.tick()
        self.assertEqual(len(cpu_calls), 1)
        self.assertEqual(len(mem_calls), 1)
        self.assertIn("cpu", cache)
        self.assertIn("memory", cache)

    def test_timings_contain_run_gatherers(self):
        fn, _ = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {}, 60)
        _, timings, _ = s.tick()
        self.assertIn("cpu", timings)
        self.assertIsInstance(timings["cpu"], float)
        self.assertGreaterEqual(timings["cpu"], 0)

    def test_gatherer_not_rerun_before_interval(self):
        fn, calls = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {}, 60)
        s.tick()
        # Immediately tick again — interval hasn't elapsed
        _, timings, _ = s.tick()
        self.assertNotIn("cpu", timings)
        self.assertEqual(len(calls), 1)

    def test_gatherer_rerun_after_interval_elapsed(self):
        fn, calls = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {"cpu": 10}, 60)
        s.tick()
        # Simulate time having passed beyond the interval
        s._last_collected["cpu"] = time.time() - 11
        _, timings, _ = s.tick()
        self.assertIn("cpu", timings)
        self.assertEqual(len(calls), 2)

    def test_cache_holds_stale_result_for_unrun_gatherer(self):
        fn, _ = _make_counter("disk")
        s = GathererScheduler({"disk": fn}, {"disk": 60}, 60)
        s.tick()
        first_cache, _ = s.tick(), None  # second tick — not due
        cache, _, _ = s.tick()
        self.assertIn("disk", cache)
        self.assertEqual(cache["disk"], {"disk": 1})  # still the first result

    def test_per_gatherer_interval_override(self):
        cpu_fn, cpu_calls = _make_counter("cpu")
        mem_fn, mem_calls = _make_counter("memory")
        intervals = {"cpu": 5, "memory": 30}
        s = GathererScheduler(
            {"cpu": cpu_fn, "memory": mem_fn},
            intervals,
            60,
        )
        s.tick()
        # Advance cpu past its 5s interval but not memory past 30s
        s._last_collected["cpu"] = time.time() - 6
        s._last_collected["memory"] = time.time() - 10
        _, timings, _ = s.tick()
        self.assertIn("cpu", timings)
        self.assertNotIn("memory", timings)
        self.assertEqual(len(cpu_calls), 2)
        self.assertEqual(len(mem_calls), 1)

    def test_prime_intervals_fire_independently(self):
        """Gatherers with prime-number intervals each fire when due,
        regardless of what the other gatherers' intervals are."""
        cpu_fn, cpu_calls = _make_counter("cpu")
        mem_fn, mem_calls = _make_counter("memory")
        intervals = {"cpu": 13, "memory": 17}
        s = GathererScheduler(
            {"cpu": cpu_fn, "memory": mem_fn},
            intervals,
            60,
        )
        s.tick()
        # Only cpu is due (13s elapsed, memory needs 17)
        s._last_collected["cpu"] = time.time() - 14
        s._last_collected["memory"] = time.time() - 10
        _, timings, _ = s.tick()
        self.assertIn("cpu", timings)
        self.assertNotIn("memory", timings)

        # Now only memory is due
        s._last_collected["cpu"] = time.time() - 5
        s._last_collected["memory"] = time.time() - 18
        _, timings, _ = s.tick()
        self.assertNotIn("cpu", timings)
        self.assertIn("memory", timings)

    def test_late_wakeup_does_not_skip_collection(self):
        """If the OS sleep ran long and now > last + interval by more than
        one interval, the gatherer fires on the next tick anyway."""
        fn, calls = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {"cpu": 10}, 60)
        s.tick()
        # Simulate a sleep that ran way over — 25 seconds elapsed instead of 10
        s._last_collected["cpu"] = time.time() - 25
        _, timings, _ = s.tick()
        self.assertIn("cpu", timings)
        self.assertEqual(len(calls), 2)

    def test_cache_returned_contains_all_ever_collected(self):
        """Cache must contain results for all gatherers even when only one ran."""
        cpu_fn, _ = _make_counter("cpu")
        mem_fn, _ = _make_counter("memory")
        s = GathererScheduler({"cpu": cpu_fn, "memory": mem_fn}, {}, 60)
        s.tick()
        # Only cpu is due next
        s._last_collected["cpu"] = time.time() - 61
        s._last_collected["memory"] = time.time() - 5
        cache, _, _ = s.tick()
        self.assertIn("cpu", cache)
        self.assertIn("memory", cache)

    def test_gatherer_result_dict_merged_into_cache(self):
        """Gatherer may return multiple keys; all must appear in cache."""
        def multi_fn():
            return {"cpustats": {"a": 1}, "cpuinfo": {"b": 2}}
        s = GathererScheduler({"cpu": multi_fn}, {}, 60)
        cache, _, _ = s.tick()
        self.assertEqual(cache["cpu"], {"cpustats": {"a": 1}, "cpuinfo": {"b": 2}})

    def test_interval_below_min_clamped(self):
        """An interval configured below MIN_INTERVAL is silently clamped up."""
        fn, _ = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {"cpu": 1}, 60)
        self.assertEqual(s._interval_for("cpu"), GathererScheduler.MIN_INTERVAL)

    def test_empty_timings_when_nothing_due(self):
        fn, _ = _make_counter("cpu")
        s = GathererScheduler({"cpu": fn}, {"cpu": 60}, 60)
        s.tick()
        _, timings, _ = s.tick()
        self.assertEqual(timings, {})

    def test_ready_false_with_multiple_gatherers_until_all_collected(self):
        cpu_fn, _ = _make_counter("cpu")
        mem_fn, _ = _make_counter("memory")
        # Make memory interval very long so manual _last_collected manipulation controls it
        s = GathererScheduler({"cpu": cpu_fn, "memory": mem_fn}, {"memory": 3600}, 60)
        # Seed last_collected for memory so it's NOT due yet on first tick
        s._last_collected["memory"] = time.time()
        # On first tick only cpu runs (memory isn't due yet)
        _, _, _ = s.tick()
        self.assertFalse(s.ready)
        # Now make memory due
        s._last_collected["memory"] = time.time() - 3601
        _, _, _ = s.tick()
        self.assertTrue(s.ready)


class TestIntervalFor(unittest.TestCase):

    def test_uses_per_gatherer_interval(self):
        fn, _ = _make_counter("disk")
        s = GathererScheduler({"disk": fn}, {"disk": 120}, 60)
        self.assertEqual(s._interval_for("disk"), 120)

    def test_falls_back_to_default_interval(self):
        fn, _ = _make_counter("disk")
        s = GathererScheduler({"disk": fn}, {}, 90)
        self.assertEqual(s._interval_for("disk"), 90)

    def test_unknown_gatherer_uses_default(self):
        s = GathererScheduler({}, {}, 45)
        self.assertEqual(s._interval_for("nonexistent"), 45)


class TestExceptionHandling(unittest.TestCase):

    def test_gatherer_exception_does_not_crash_tick(self):
        """An exception in one gatherer must not prevent others from running."""
        calls = []
        def bad_fn():
            raise RuntimeError("simulated failure")
        def good_fn():
            calls.append("good")
            return {"ok": True}
        s = GathererScheduler({"bad": bad_fn, "good": good_fn}, {}, 5)
        cache, timings, errors = s.tick()
        self.assertIn("good", calls)
        self.assertEqual(cache["good"], {"ok": True})
        self.assertIn("bad", errors)

    def test_gatherer_exception_populates_errors_dict(self):
        """Exception details should be captured in errors dict."""
        def raiser():
            raise ValueError("bad parse")
        s = GathererScheduler({"x": raiser}, {}, 5)
        _, _, errors = s.tick()
        self.assertIn("x", errors)
        self.assertEqual(errors["x"]["error"], "ValueError")
        self.assertIn("bad parse", errors["x"]["message"])

    def test_gatherer_cache_is_none_after_exception(self):
        """Failed gatherer should have cache[name] = None."""
        def raiser():
            raise OSError("gone")
        s = GathererScheduler({"x": raiser}, {}, 5)
        cache, _, _ = s.tick()
        self.assertIsNone(cache["x"])

    def test_error_cleared_on_recovery(self):
        """Error should be removed from errors dict on next successful collection."""
        fail = True
        def sometimes_fail():
            nonlocal fail
            if fail:
                raise RuntimeError("transient")
            return {"x": 1}
        s = GathererScheduler({"g": sometimes_fail}, {}, 5)
        _, _, errors = s.tick()
        self.assertIn("g", errors)
        fail = False
        # Force interval to elapse so gatherer is due again
        s._last_collected["g"] = 0
        cache, _, errors = s.tick()
        self.assertNotIn("g", errors)
        self.assertEqual(cache["g"], {"x": 1})

    def test_timing_and_last_collected_updated_on_error(self):
        """Timing and _last_collected should be recorded even on error."""
        def raiser():
            raise RuntimeError("oops")
        s = GathererScheduler({"x": raiser}, {}, 5)
        _, timings, _ = s.tick()
        self.assertIn("x", timings)
        self.assertIn("x", s._last_collected)
        # timing should be positive
        self.assertGreater(timings["x"], 0)


if __name__ == "__main__":
    unittest.main()
