# ClearBed model card

Trained: 2026-10-07T02:35:18.281025+00:00

## Data

Synthetic Synthea inpatient stays for Massachusetts, joined to a seeded labeling function (`dbt/seeds/labeling_rules.csv`). CMS facility data is not an input to these models.

Gender and race are excluded from the model matrix and reported only in `reports/fairness.md`.

The split is the earliest 70% of admissions for training, the next 15% for validation (isotonic calibration), and the last 15% for test.

## Metrics (held-out test)

| Model | Metric | Value |
| --- | --- | --- |
| A stuck risk | AUROC | 0.7162035920925748 |
| A stuck risk | AUPRC | 0.5916255076781034 |
| A stuck risk | Brier | 0.19784295949976577 |
| B barrier type | macro-F1 | 0.5782684868819322 |
| C avoidable days | MAE | 2.655566877356367 |

## Limitations

These labels are a noisy function of the same admission features. High discrimination is expected and is **not** evidence the model would rank real discharge delays. Synthea has no discharge disposition.

Do not use the score as a clinical or coverage determination. A case manager approves every referral. The avoidable-day model predicts the synthetic label, not a measured delay.

Replace the labeling function with MIMIC-IV `admissions.discharge_location` before any hospital pilot that claims predictive accuracy.

## Intended use

Rank a morning census so case management looks first at stays the rules and the model both consider likely to wait on placement, payer, guardianship, or home services.
