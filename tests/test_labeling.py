"""Tests for the auditable labeling function and the workflow router."""

from __future__ import annotations

import pandas as pd

from clearbed.features.labeling import assign_label, assign_labels, route_barrier, unit_interval


def _rules() -> list[dict[str, object]]:
    return [
        {
            "rule_id": "R_POST",
            "priority": 10,
            "min_age": 75,
            "max_age": None,
            "condition_groups": "hip_fracture|stroke",
            "payer_types": None,
            "requires_dementia": 0,
            "requires_lives_alone": 0,
            "requires_home_o2": 0,
            "requires_chf_or_copd": 0,
            "barrier_type": "post_acute_placement",
            "probability": 1,
            "avoidable_min": 2,
            "avoidable_max": 2,
            "notes": "certain placement",
        },
        {
            "rule_id": "R_NONE",
            "priority": 1000,
            "min_age": None,
            "max_age": None,
            "condition_groups": None,
            "payer_types": None,
            "requires_dementia": 0,
            "requires_lives_alone": 0,
            "requires_home_o2": 0,
            "requires_chf_or_copd": 0,
            "barrier_type": "none",
            "probability": 1,
            "avoidable_min": 0,
            "avoidable_max": 0,
            "notes": "default",
        },
    ]


def test_unit_interval_is_stable() -> None:
    assert unit_interval("stay-1") == unit_interval("stay-1")
    assert 0 <= unit_interval("stay-1") < 1


def test_rule_assigns_stuck_placement() -> None:
    stay = {
        "stay_id": "s1",
        "age_at_admit": 82,
        "condition_group": "hip_fracture",
        "payer_type": "medicare",
        "flag_dementia": 0,
        "lives_alone_proxy": 1,
        "flag_home_o2": 0,
        "flag_chf": 0,
        "flag_copd": 0,
    }
    labeled = assign_label(stay, _rules())
    assert labeled["barrier_type"] == "post_acute_placement"
    assert labeled["avoidable_days"] == 2
    assert labeled["is_stuck"] == 1


def test_assign_labels_frame() -> None:
    stays = pd.DataFrame(
        [
            {
                "stay_id": "s1",
                "age_at_admit": 40,
                "condition_group": "other",
                "payer_type": "commercial",
                "flag_dementia": 0,
                "lives_alone_proxy": 0,
                "flag_home_o2": 0,
                "flag_chf": 0,
                "flag_copd": 0,
            }
        ]
    )
    out = assign_labels(stays, pd.DataFrame(_rules()))
    assert out.loc[0, "barrier_type"] == "none"
    assert out.loc[0, "is_stuck"] == 0


def test_route_prefers_guardianship_over_placement() -> None:
    route = route_barrier(
        {
            "age_at_admit": 88,
            "condition_group": "hip_fracture",
            "payer_type": "medicare",
            "flag_dementia": 1,
            "lives_alone_proxy": 1,
            "flag_chf": 0,
            "flag_copd": 0,
            "flag_home_o2": 0,
            "predicted_barrier": "none",
        }
    )
    assert route == "guardianship_capacity"


def test_route_uses_model_when_no_rule_fires() -> None:
    route = route_barrier(
        {
            "age_at_admit": 50,
            "condition_group": "other",
            "payer_type": "commercial",
            "flag_dementia": 0,
            "lives_alone_proxy": 0,
            "flag_chf": 0,
            "flag_copd": 0,
            "flag_home_o2": 0,
            "predicted_barrier": "home_services",
        }
    )
    assert route == "home_services"
