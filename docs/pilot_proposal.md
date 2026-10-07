# ClearBed 60-day pilot

**ClearBed · Free 60-day pilot · Deva Choppa · 617-602-6800**

One Boston hospital. No fee for 60 days. The pilot shows, on admission, which inpatients are likely to wait on a nursing-home bed, a payer decision, a guardian, or home services, and what that wait costs in bed-days.

## What the hospital gets

- A morning worklist ranked by stuck risk, with the five reasons for each flag written in plain language.
- Facility matches against real Massachusetts skilled nursing facilities from CMS Care Compare, scored by payer, care needs, open beds, and distance. The score breakdown is visible.
- A referral draft that marks missing items `[NEEDS INPUT]` and cites the rule it checked, including Medicare's three-day inpatient stay.
- A leadership view of projected avoidable bed-days. The dollar figure uses an assumed cost per bed-day (default $2,500) and is labeled as an assumption.
- An audit log of every approval. Nothing is marked sent until a case manager approves it. The pilot build does not transmit packets to facilities.

## What we need from the hospital

- A case-management champion and a finance or throughput partner who will look at the leadership view once a week.
- A read-only shadow of current inpatients for the last two weeks of the pilot, or agreement to keep running on synthetic data for the full 60 days if data-use review is still open.
- One hour to confirm which payer and guardianship rules the compliance team wants cited. The notes in `knowledge/` are drafts and must be verified before anyone relies on them.

## How the 60 days run

1. **Days 1–15.** Install on synthetic Synthea patients and the CMS facility file. Case management clicks through the worklist, a plan, and an approval. We fix wording and filters from that session.
2. **Days 16–40.** Shadow mode if the hospital has approved a data path. Scores are compared with the delays the team already tracks. The model is not used as a clinical or coverage decision.
3. **Days 41–60.** Weekly bed-day review with the champion. We write down which flags were useful, which were noise, and whether a paid deployment is worth scoping.

## What this pilot does not claim

The current model is trained on a documented synthetic labeling function. Synthea has no discharge disposition. Discrimination on that label is not evidence about real discharge delays. A production version replaces the label with the hospital's own disposition, or with MIMIC-IV `admissions.discharge_location` during development.

On-screen figures about Massachusetts discharge delays, including "1,000+ patients" and "~$400M a year," must be checked against the current Massachusetts Health & Hospital Association brief before they appear in a public video or a board slide. This proposal does not treat those figures as a measured result from ClearBed.

Capability flags for dialysis, trach/vent, behavioral health, bariatric care, and response time are synthetic. They are labeled in the product.

## Success, at day 60

- Case managers can explain a flag without opening the model.
- Every drafted packet shown in the pilot either cites a source or is marked as missing information.
- Zero referrals leave the approval queue without a person.
- The champion can point at the bed-day number and the cost assumption and say whether it is the right conversation for their CFO.

## Contact

Deva Choppa · 617-602-6800

ClearBed is not a medical device.
