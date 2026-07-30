from threading import Lock
from time import monotonic

from psutil import net_io_counters


class NetworkRateSampler:
    def __init__(
        self,
        counter_reader=net_io_counters,
        clock=monotonic,
        min_interval=0.25,
    ):
        self._counter_reader = counter_reader
        self._clock = clock
        self._min_interval = max(0.0, float(min_interval))
        self._lock = Lock()
        self._last_received = None
        self._last_sent = None
        self._last_time = None
        self._last_rates = (0.0, 0.0)
        self._prime()

    def _read(self):
        counters = self._counter_reader()
        if counters is None:
            raise RuntimeError("Network counters are unavailable")
        return int(counters.bytes_recv), int(counters.bytes_sent)

    def _prime(self):
        try:
            received, sent = self._read()
            sampled_at = self._clock()
        except Exception:
            return
        self._last_received = received
        self._last_sent = sent
        self._last_time = sampled_at

    def sample(self):
        with self._lock:
            try:
                received, sent = self._read()
                sampled_at = self._clock()
            except Exception:
                return self._last_rates

            if self._last_time is None:
                self._last_received = received
                self._last_sent = sent
                self._last_time = sampled_at
                return self._last_rates

            elapsed = sampled_at - self._last_time
            if 0 < elapsed < self._min_interval:
                return self._last_rates

            if elapsed <= 0:
                download_rate = upload_rate = 0.0
            else:
                download_rate = max(0, received - self._last_received) / elapsed
                upload_rate = max(0, sent - self._last_sent) / elapsed

            self._last_received = received
            self._last_sent = sent
            self._last_time = sampled_at
            self._last_rates = (download_rate, upload_rate)
            return self._last_rates


system_network_rate = NetworkRateSampler()
