"""Deterministic standardized scenario generation for Phase 9."""

from __future__ import annotations

import hashlib
import math

from app.concurrent_simulation.contracts import (
    CONCURRENT_SIMULATION_CONTRACT_VERSION,
    SCENARIO_GENERATOR_ID,
    ScenarioBatch,
    ScenarioBatchRequest,
    UncertaintyScenario,
)

_UNIFORM_BITS = 52
_UNIFORM_DENOMINATOR = (1 << _UNIFORM_BITS) + 1


def generate_scenario_batch(request: ScenarioBatchRequest) -> ScenarioBatch:
    """Generate repeatable shared draws without mutating the Phase 8 request."""
    if not isinstance(request, ScenarioBatchRequest):
        raise TypeError("request must be a ScenarioBatchRequest")
    scenarios = tuple(
        _generate_scenario(request, scenario_index)
        for scenario_index in range(request.scenario_count)
    )
    return ScenarioBatch(
        request=request,
        generator_id=SCENARIO_GENERATOR_ID,
        scenarios=scenarios,
    )


def _generate_scenario(
    request: ScenarioBatchRequest,
    scenario_index: int,
) -> UncertaintyScenario:
    return UncertaintyScenario(
        scenario_index=scenario_index,
        scenario_seed=_scenario_seed(request.root_seed, scenario_index),
        shared_pace_z=_standard_normal(
            request.root_seed,
            scenario_index,
            draw_index=0,
        ),
        pit_loss_z=_standard_normal(
            request.root_seed,
            scenario_index,
            draw_index=1,
        ),
        lap_time_residual_z=tuple(
            (
                lap_number,
                _standard_normal(
                    request.root_seed,
                    scenario_index,
                    draw_index=offset + 2,
                ),
            )
            for offset, lap_number in enumerate(request.lap_numbers)
        ),
    )


def _scenario_seed(root_seed: int, scenario_index: int) -> int:
    digest = _digest(root_seed, scenario_index, "scenario-seed")
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _standard_normal(
    root_seed: int,
    scenario_index: int,
    *,
    draw_index: int,
) -> float:
    digest = _digest(root_seed, scenario_index, f"draw-{draw_index}")
    uniform_a = _open_unit_interval(digest[:8])
    uniform_b = _open_unit_interval(digest[8:16])
    return math.sqrt(-2.0 * math.log(uniform_a)) * math.cos(
        math.tau * uniform_b
    )


def _digest(root_seed: int, scenario_index: int, channel: str) -> bytes:
    payload = "\x00".join(
        (
            CONCURRENT_SIMULATION_CONTRACT_VERSION,
            SCENARIO_GENERATOR_ID,
            str(root_seed),
            str(scenario_index),
            channel,
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).digest()


def _open_unit_interval(chunk: bytes) -> float:
    integer = int.from_bytes(chunk, byteorder="big", signed=False)
    mantissa = integer >> (64 - _UNIFORM_BITS)
    return (mantissa + 1) / _UNIFORM_DENOMINATOR
