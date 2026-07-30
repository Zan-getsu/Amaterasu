from types import SimpleNamespace

import pytest

from bot.helper.ext_utils.network_utils import NetworkRateSampler


def _sequence_reader(values):
    values = iter(values)
    return lambda: next(values)


def _sequence_clock(values):
    values = iter(values)
    return lambda: next(values)


def test_network_rates_use_counter_delta_over_elapsed_time():
    sampler = NetworkRateSampler(
        counter_reader=_sequence_reader(
            [
                SimpleNamespace(bytes_recv=1_000, bytes_sent=500),
                SimpleNamespace(bytes_recv=5_000, bytes_sent=1_500),
            ]
        ),
        clock=_sequence_clock([10.0, 12.0]),
        min_interval=0,
    )

    assert sampler.sample() == (2_000.0, 500.0)


def test_network_sampler_establishes_a_baseline_after_initial_read_failure():
    calls = iter(
        [
            RuntimeError("not ready"),
            SimpleNamespace(bytes_recv=1_000, bytes_sent=500),
            SimpleNamespace(bytes_recv=2_000, bytes_sent=1_000),
        ]
    )

    def reader():
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    sampler = NetworkRateSampler(
        counter_reader=reader,
        clock=_sequence_clock([10.0, 12.0]),
        min_interval=0,
    )

    assert sampler.sample() == (0.0, 0.0)
    assert sampler.sample() == (500.0, 250.0)


def test_network_counter_reset_never_produces_negative_rates():
    sampler = NetworkRateSampler(
        counter_reader=_sequence_reader(
            [
                SimpleNamespace(bytes_recv=5_000, bytes_sent=3_000),
                SimpleNamespace(bytes_recv=100, bytes_sent=5_000),
            ]
        ),
        clock=_sequence_clock([10.0, 12.0]),
        min_interval=0,
    )

    assert sampler.sample() == (0.0, 1_000.0)


def test_short_interval_returns_cached_rates_without_moving_baseline():
    sampler = NetworkRateSampler(
        counter_reader=_sequence_reader(
            [
                SimpleNamespace(bytes_recv=1_000, bytes_sent=500),
                SimpleNamespace(bytes_recv=2_000, bytes_sent=1_000),
                SimpleNamespace(bytes_recv=5_000, bytes_sent=2_500),
            ]
        ),
        clock=_sequence_clock([10.0, 10.1, 11.0]),
        min_interval=0.25,
    )

    assert sampler.sample() == (0.0, 0.0)
    assert sampler.sample() == (4_000.0, 2_000.0)


@pytest.mark.asyncio
async def test_status_system_metrics_render_dl_and_up_rates(monkeypatch):
    from bot.helper.ext_utils import status_utils

    async def no_tasks(*_args):
        return []

    monkeypatch.setattr(status_utils, "get_specific_tasks", no_tasks)
    monkeypatch.setattr(
        status_utils.system_network_rate,
        "sample",
        lambda: (1_024.0, 2_048.0),
    )
    monkeypatch.setattr(status_utils, "cpu_percent", lambda: 12.5)
    monkeypatch.setattr(
        status_utils,
        "virtual_memory",
        lambda: SimpleNamespace(percent=25.0),
    )
    monkeypatch.setattr(
        status_utils,
        "disk_usage",
        lambda _path: SimpleNamespace(free=10_000),
    )

    message, _buttons = await status_utils.get_readable_message(123, False)

    assert "DL       : ↓ 1.00KB/s" in message
    assert "UP       : ↑ 2.00KB/s" in message
