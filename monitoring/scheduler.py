"""Gatherer scheduling for configurable per-subsystem collection intervals.

GathererScheduler tracks when each named gatherer was last collected and
only re-collects it when its configured interval has elapsed.

The main loop wakes up on a fixed 1-second base tick (BASE_TICK) regardless
of how gatherer intervals are configured. On each wake-up, the scheduler
checks every gatherer using an elapsed-time comparison (now - last >= interval)
to determine which are due. This means:

  - Gatherer intervals do not need to be multiples of each other or of any
    common base — prime-valued intervals (13s, 17s, 37s) work correctly.
  - If the OS sleep runs long (sleep(1) returns after 1.01s or more), the
    >= comparison still fires the gatherer on the next opportunity without
    permanently drifting or skipping collections.

Typical usage in a daemon loop::

    scheduler = GathererScheduler(gatherers, cfg.gatherer_intervals, cfg.run_interval)
    while True:
        cache, timings = scheduler.tick()
        if scheduler.ready:
            json_out = assemble(cache)
        time.sleep(scheduler.BASE_TICK)
"""
import time


class GathererScheduler:
    """Schedules collection of gatherer functions at independent intervals.

    Each gatherer is a callable that takes no arguments and returns a dict
    of JSON key/value pairs (e.g. {"cpustats": {...}, "cpuinfo": {...}}).

    Intervals are specified per gatherer name; gatherers not present in
    *intervals* fall back to *default_interval*. The caller is responsible
    for sleeping BASE_TICK between tick() calls — the scheduler itself does
    not sleep.
    """

    MIN_INTERVAL = 5   # seconds — minimum allowed per-gatherer interval
    MIN_BASE_TICK = 1  # seconds — minimum allowed base tick

    def __init__(self, gatherers, intervals, default_interval, base_tick=1):
        """
        Args:
            gatherers: dict of name -> callable() -> dict, in desired order.
            intervals: dict of name -> int seconds (per-gatherer overrides).
            default_interval: fallback interval for gatherers not in intervals.
            base_tick: how often (seconds) the main loop wakes to check if any
                gatherer is due. Smaller = lower variance in firing time but
                more frequent loop iterations. Larger = coarser timing but
                lighter. Must be >= MIN_BASE_TICK. Default: 1.
        """
        self._gatherers = gatherers
        self._intervals = intervals
        self._default_interval = max(self.MIN_INTERVAL, default_interval)
        self.base_tick = max(self.MIN_BASE_TICK, base_tick)
        self._last_collected = {}  # name -> float (unix timestamp of last run)
        self._cache = {}           # name -> dict (most recent result)

    def _interval_for(self, name):
        """Return the effective collection interval (seconds) for a gatherer."""
        raw = self._intervals.get(name, self._default_interval)
        return max(self.MIN_INTERVAL, raw)

    def tick(self):
        """Check all gatherers and collect any whose interval has elapsed.

        Uses >= comparison against wall-clock elapsed time so that a late
        wake-up (sleep ran long) never causes a collection to be permanently
        skipped — it simply fires on the next tick() call.

        Returns:
            (cache, timings) tuple where:
                cache   — dict mapping gatherer name to its most recent result.
                          Includes all gatherers ever collected, not just this
                          tick. Callers should check scheduler.ready before
                          using the cache if they need all gatherers present.
                timings — dict mapping gatherer name to float seconds elapsed.
                          Only contains gatherers that ran this tick.
        """
        now = time.time()
        timings = {}
        for name, fn in self._gatherers.items():
            if now - self._last_collected.get(name, 0) >= self._interval_for(name):
                t0 = time.time()
                self._cache[name] = fn()
                self._last_collected[name] = time.time()
                timings[name] = time.time() - t0
        return dict(self._cache), timings

    @property
    def ready(self):
        """True if every registered gatherer has been collected at least once."""
        return all(name in self._cache for name in self._gatherers)
