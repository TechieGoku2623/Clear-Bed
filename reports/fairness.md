# Fairness snapshot

Gender and race were **not** used as model inputs. Payer type was.
Groups with fewer than 20 test stays, or with only one outcome, are marked insufficient.
These figures describe a synthetic labeling function. They are not a clinical fairness claim.

## gender

| Group | n | positive rate | AUROC |
| --- | --- | --- | --- |
| F | 196 | 33.2% | 0.701 |
| M | 184 | 38.6% | 0.734 |

## race

| Group | n | positive rate | AUROC |
| --- | --- | --- | --- |
| asian | 44 | 20.5% | 0.706 |
| black | 26 | 30.8% | 0.493 |
| hawaiian | 13 | 53.8% | insufficient |
| other | 1 | 0.0% | insufficient |
| white | 296 | 37.8% | 0.714 |

## payer_type

| Group | n | positive rate | AUROC |
| --- | --- | --- | --- |
| commercial | 89 | 15.7% | 0.528 |
| dual | 54 | 25.9% | 0.670 |
| medicaid | 58 | 44.8% | 0.444 |
| medicare | 173 | 44.5% | 0.751 |
| none | 6 | 83.3% | insufficient |
