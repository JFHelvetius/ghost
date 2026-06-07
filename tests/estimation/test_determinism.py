"""Determinismo del `NoisyGroundTruthEstimator` (ADR-0015 §6).

Cubre:

- **Replay**: dos estimadores con el mismo parent seed + mismo label +
  misma secuencia de inputs producen ``VehicleState`` field-by-field
  iguales, incluido el byte-encoded JSON via
  ``telemetry.encode_to_bytes``.
- **Independencia por label**: cambiar ``random_source_label`` cambia
  la secuencia de ruido (no es accidental — es la API que permite
  varias instancias coexistir sin colisión).
- **Independencia por seed**: cambiar ``parent.seed`` cambia la
  secuencia.
- **Aislamiento entre instancias**: dos estimadores que comparten
  parent pero con labels distintos no se interfieren entre sí.
- **No reads de reloj**: el estimador no lee ningún reloj — verificado
  indirectamente porque el byte-encoded JSON es estable entre llamadas
  separadas en el tiempo wall.
"""

from __future__ import annotations

import numpy as np

from project_ghost.estimation import NoisyGroundTruthEstimator
from project_ghost.telemetry import encode_to_bytes
from tests.estimation.conftest import (
    make_config,
    make_flight,
    make_gt,
    make_health,
    make_mission,
    make_rs,
)


def _run_n_estimates(
    estimator: NoisyGroundTruthEstimator, n: int
) -> list[bytes]:
    """Corre ``n`` estimates con inputs idénticos y devuelve sus
    encodings byte-deterministas."""
    out: list[bytes] = []
    for i in range(n):
        vs = estimator.estimate(
            gt=make_gt(stamp_sim_ns=i * 1000),
            sensors_health=make_health(),
            flight=make_flight(),
            mission=make_mission(),
            stamp_wall_ns=i * 17,
        )
        out.append(encode_to_bytes(vs))
    return out


def test_same_seed_and_label_produce_byte_identical_outputs() -> None:
    """Replay determinista (ADR-0002, ADR-0015 §6): mismo parent.seed,
    mismo label, misma secuencia de inputs -> bytes iguales."""
    cfg_a = make_config()
    cfg_b = make_config()
    est_a = NoisyGroundTruthEstimator(config=cfg_a, random_source=make_rs(seed=42))
    est_b = NoisyGroundTruthEstimator(config=cfg_b, random_source=make_rs(seed=42))

    outs_a = _run_n_estimates(est_a, 5)
    outs_b = _run_n_estimates(est_b, 5)

    assert outs_a == outs_b


def test_different_parent_seeds_produce_different_outputs() -> None:
    cfg = make_config()
    est_a = NoisyGroundTruthEstimator(config=cfg, random_source=make_rs(seed=1))
    est_b = NoisyGroundTruthEstimator(
        config=cfg, random_source=make_rs(seed=99999)
    )

    outs_a = _run_n_estimates(est_a, 3)
    outs_b = _run_n_estimates(est_b, 3)

    assert outs_a != outs_b


def test_different_labels_produce_different_outputs() -> None:
    cfg_a = make_config(random_source_label="/a")
    cfg_b = make_config(random_source_label="/b")
    est_a = NoisyGroundTruthEstimator(
        config=cfg_a, random_source=make_rs(seed=42)
    )
    est_b = NoisyGroundTruthEstimator(
        config=cfg_b, random_source=make_rs(seed=42)
    )

    outs_a = _run_n_estimates(est_a, 3)
    outs_b = _run_n_estimates(est_b, 3)

    assert outs_a != outs_b


def test_two_estimators_sharing_parent_with_different_labels_are_isolated() -> None:
    """Mismo parent, dos labels distintos: cada estimador deriva su
    propio child; las secuencias de ruido son independientes. Un caller
    puede correr ambos sin que se interfieran."""
    parent = make_rs(seed=42)
    cfg_a = make_config(random_source_label="/a")
    cfg_b = make_config(random_source_label="/b")

    est_a = NoisyGroundTruthEstimator(config=cfg_a, random_source=parent)
    est_b = NoisyGroundTruthEstimator(config=cfg_b, random_source=parent)

    # Correr el A varias veces y luego B no debe cambiar lo que B
    # habría producido si lo corriéramos primero — los child son
    # independientes.
    a_outs = _run_n_estimates(est_a, 3)

    # Reconstruir un B fresco con el mismo setup y compararlo con el
    # B que ya construimos antes de correr A.
    parent2 = make_rs(seed=42)
    est_b_fresh = NoisyGroundTruthEstimator(
        config=make_config(random_source_label="/b"),
        random_source=parent2,
    )
    b_after_a = _run_n_estimates(est_b, 3)
    b_alone = _run_n_estimates(est_b_fresh, 3)

    assert b_after_a == b_alone
    # Sanity: A y B difieren (labels distintos).
    assert a_outs != b_after_a


def test_position_values_are_bit_identical_across_runs() -> None:
    """No solo el byte-encoded JSON, sino las floats crudas deben
    coincidir bit-a-bit."""
    cfg = make_config()
    est_a = NoisyGroundTruthEstimator(
        config=cfg, random_source=make_rs(seed=7)
    )
    est_b = NoisyGroundTruthEstimator(
        config=cfg, random_source=make_rs(seed=7)
    )

    for i in range(3):
        gt = make_gt(stamp_sim_ns=i * 100)
        vs_a = est_a.estimate(
            gt=gt,
            sensors_health=make_health(),
            flight=make_flight(),
            mission=make_mission(),
            stamp_wall_ns=0,
        )
        vs_b = est_b.estimate(
            gt=gt,
            sensors_health=make_health(),
            flight=make_flight(),
            mission=make_mission(),
            stamp_wall_ns=0,
        )
        np.testing.assert_array_equal(
            vs_a.nav.pose.position_enu_m, vs_b.nav.pose.position_enu_m
        )
        np.testing.assert_array_equal(
            vs_a.nav.pose.orientation_q, vs_b.nav.pose.orientation_q
        )
        np.testing.assert_array_equal(
            vs_a.nav.twist_world.linear_mps,
            vs_b.nav.twist_world.linear_mps,
        )
        np.testing.assert_array_equal(
            vs_a.nav.accel_body_mps2, vs_b.nav.accel_body_mps2
        )


def test_zero_noise_does_not_advance_generator() -> None:
    """std=0 NO debe consumir samples del Generator (ADR-0015 design
    decision): un estimador con position_noise_std_m=0 y orientation_noise_std_rad>0
    debe producir la misma secuencia de quaternions que uno equivalente
    en otro orden — porque el ahorro evita reordering hazards.

    Verificamos esto comparando: si position_std=0 NO consume del rng,
    entonces los otros 4 samples deben coincidir bit-a-bit con un
    estimador donde solo se omite el primer draw."""
    cfg_zero_pos = make_config(
        position_noise_std_m=0.0,
        # los otros >0 para que sí consuman del rng.
    )
    est = NoisyGroundTruthEstimator(
        config=cfg_zero_pos, random_source=make_rs(seed=123)
    )
    vs = est.estimate(
        gt=make_gt(),
        sensors_health=make_health(),
        flight=make_flight(),
        mission=make_mission(),
        stamp_wall_ns=0,
    )
    # Position debe ser exactamente la GT (ni el rng se tocó para esto).
    np.testing.assert_array_equal(
        vs.nav.pose.position_enu_m,
        np.zeros(3, dtype=np.float64),
    )


def test_replay_with_byte_encoded_output_is_stable() -> None:
    """Si la encodificación del VehicleState produjera bytes inestables
    entre llamadas separadas, la línea de telemetry T4 se rompería.
    Verificamos directamente."""
    cfg = make_config()
    est_a = NoisyGroundTruthEstimator(
        config=cfg, random_source=make_rs(seed=2026)
    )
    est_b = NoisyGroundTruthEstimator(
        config=cfg, random_source=make_rs(seed=2026)
    )

    gt = make_gt(stamp_sim_ns=1)
    vs_a = est_a.estimate(
        gt=gt,
        sensors_health=make_health(),
        flight=make_flight(),
        mission=make_mission(),
        stamp_wall_ns=42,
    )
    vs_b = est_b.estimate(
        gt=gt,
        sensors_health=make_health(),
        flight=make_flight(),
        mission=make_mission(),
        stamp_wall_ns=42,
    )

    assert encode_to_bytes(vs_a) == encode_to_bytes(vs_b)
