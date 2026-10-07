"""Time-ordered split and the feature matrix exclude demographic columns."""

from __future__ import annotations

import pandas as pd

from clearbed.ml.feature_labels import model_feature_columns
from clearbed.ml.train import design_matrix, time_split


def test_time_split_is_ordered() -> None:
    frame = pd.DataFrame(
        {
            "admit_ts": pd.date_range("2024-01-01", periods=10, freq="D"),
            "stay_id": [str(i) for i in range(10)],
        }
    )
    split = time_split(frame)
    assert split.train["admit_ts"].max() <= split.validate["admit_ts"].min()
    assert split.validate["admit_ts"].max() <= split.test["admit_ts"].min()
    assert len(split.train) + len(split.validate) + len(split.test) == 10


def test_design_matrix_drops_gender_and_race() -> None:
    columns = model_feature_columns()
    assert "gender" not in columns
    assert "race" not in columns
    frame = pd.DataFrame(
        {
            "age_at_admit": [80],
            "admit_month": [1],
            "admit_dow": [2],
            "prior_admits_12m": [0],
            "prior_ed_visits_12m": [1],
            "n_active_meds": [3],
            "expected_los_days": [5],
            "flag_dementia": [0],
            "flag_ckd_dialysis": [0],
            "flag_copd": [0],
            "flag_chf": [1],
            "flag_obesity": [0],
            "flag_behavioral": [0],
            "flag_substance": [0],
            "flag_home_o2": [0],
            "lives_alone_proxy": [1],
            "condition_group": ["hip_fracture"],
            "payer_type": ["medicare"],
            "age_band": ["75-84"],
            "gender": ["F"],
            "race": ["white"],
        }
    )
    matrix, names = design_matrix(frame)
    assert "gender" not in names
    assert "race" not in names
    assert matrix.shape[0] == 1
