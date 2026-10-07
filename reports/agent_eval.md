# ClearBed agent evaluation

Result: **PASS**

- Golden cases: 25
- Citation coverage: 100.0% (floor 95%)
- Hard-filter violations: 0
- Latency p50: 0.146s
- Latency p95: 0.151s
- Groq blocked when DATA_MODE=real: True

Labels and patients in this run are synthetic. The mock model is not a clinical judge.

## Cases

- PASS g01: route guardianship_capacity expected guardianship_capacity
- PASS g02: route post_acute_placement expected post_acute_placement
- PASS g03: route post_acute_placement expected post_acute_placement
- PASS g04: route post_acute_placement expected post_acute_placement
- PASS g05: route payer_pending expected payer_pending
- PASS g06: route payer_pending expected payer_pending
- PASS g07: route home_services expected home_services
- PASS g08: route home_services expected home_services
- PASS g09: route home_services expected home_services
- PASS g10: route none expected none
- PASS g11: route post_acute_placement expected post_acute_placement
- PASS g12: route guardianship_capacity expected guardianship_capacity
- PASS g13: blocked=True reasons=['no open beds']
- PASS g14: blocked=True reasons=['payer not accepted']
- PASS g15: blocked=True reasons=['dialysis need not met']
- PASS g16: blocked=True reasons=['beyond max distance']
- PASS g17: blocked=False reasons=[]
- PASS g18: blocked=True reasons=['trach/vent need not met']
- PASS g19: 2 findings
- PASS g20: 2 findings
- PASS g21: 2 findings
- PASS g22: 1 findings
- PASS g23: unsupported=['ebola'] judge={"unsupported": []}
- PASS g24: unsupported=[] judge={"unsupported": []}
- PASS g25: kept='PASRR is required before admission.'
- PASS graph routes, hard filters, and approval interrupt
