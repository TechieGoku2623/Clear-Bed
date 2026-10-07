# ClearBed demo video (3:00)

Format: 1920×1080 screen recording (OBS or Loom) plus voiceover. AI-generated shots are used only for the intro, transition, and outro. Show the real app for everything else.

Record the app at 1080p with a **125% browser zoom** so the type is readable. Cut each scene tight. Do not leave loading spinners in the cut; trim the wait while the agent runs.

Add a small corner badge on every app scene: **Synthetic patient data — demo.** The app already renders this badge. Do not cover it with the recording overlay.

## Scene by scene

| Time | On screen | Voiceover |
| --- | --- | --- |
| 0:00–0:15 | AI shot 1 (hospital corridor at night), then text overlay: "1,000+ patients wait for discharge every day in MA hospitals" (cite MHA) | "Every day, more than a thousand patients in Massachusetts hospitals are medically ready to leave, but can't." |
| 0:15–0:30 | AI shot 2 (case manager at a desk), then overlay: "~$400M a year, per MHA" | "They're waiting on a nursing home bed, an insurance approval, or a guardian. Case managers chase it all by phone and fax." |
| 0:30–0:50 | ClearBed Leadership dashboard: KPIs, avoidable bed-days, cost | "This is ClearBed. On day one, it shows leadership how many bed-days the hospital is about to lose, and what it'll cost." |
| 0:50–1:15 | Worklist sorted by risk; filter to High; hover over a patient | "Case managers get a worklist ranked by who's likely to get stuck, flagged on admission instead of on day six." |
| 1:15–1:40 | Patient detail: risk gauge, top 5 reasons | "Every flag is explained: age, hip fracture, lives alone, Medicare with a needed skilled stay. No black box." |
| 1:40–2:10 | Click Generate plan: map with real US facilities near the hospital, score breakdown | "The agent matches real United States skilled nursing facilities by payer, care needs, open beds and distance from this hospital, and shows why each one ranks where it does." |
| 2:10–2:30 | Draft packet: [NEEDS INPUT] highlighted, rules citation | "It drafts the referral packet, flags what's missing, and checks rules like Medicare's three-day stay with citations. It never invents clinical facts." |
| 2:30–2:45 | Click Approve: status changes to Sent; dashboard updates | "Nothing goes out without a human approving it. Every action is logged." |
| 2:45–3:00 | AI shot 3 (sunrise and an empty, clean bed), then end card: "ClearBed · Free 60-day pilot · Deva Choppa · 617-602-6800" | "Fewer stuck patients, more open beds. I'm looking for one Boston hospital to pilot this. Let's talk." |

Before you publish, confirm the two on-screen figures against the current Massachusetts Health & Hospital Association (MHA) discharge-delay brief. Keep the "cite MHA" line in the overlay so a buyer can see the source.

## What to click in the app

Start the stack with `make api` and `make ui` after `make all`. Open Leadership first so the recording begins on the number, then move to the patient.

1. **0:30 Leadership.** Open Leadership. Leave the synthetic banner and the corner badge visible. Pause on census, high-risk count, projected avoidable bed-days, and the cost estimate. The cost caption must stay visible: it is an assumption, not a finance-system figure.
2. **0:50 Worklist.** Switch to Worklist. The table is already sorted by stuck probability. Set the tier filter to High so the ranking is obvious. On this scored census the High rows are a home-services stay and a guardianship stay, not a placement stay. Click **Open placement demo**. That opens the Medicare post-acute stay the map is built for (ACS or heart failure, age band 75–84). Day of stay versus expected length of stay should be readable before you cut.
3. **1:15 Patient.** Open that stay. Hold on the risk gauge and the five plain-English reasons. Do not scroll past them until the line finishes.
4. **1:40 Plan.** Click **Generate plan**. Cut out the wait. Land on the map (hospital pin plus facilities) and the score breakdown columns: distance, rating, open beds, response speed.
5. **2:10 Packet and rules.** Show the draft with `[NEEDS INPUT]` highlighted, the missing-items checklist, and one payer finding whose citation link is visible (Medicare three-day stay).
6. **2:30 Approve.** Click **Approve** on one facility. The timeline moves to Sent. Cut back to Leadership so the referral funnel has changed. Do not approve a second facility in this cut.

Nothing in the recording sends a referral without that click. If a packet is still generating, trim; do not show a spinner.

## AI video prompts

Use Veo, Sora, Runway, or Kling. These shots are only the intro, the problem transition, and the outro. The product scenes are the real app.

### Shot 1: Opening (8 sec)

Cinematic slow dolly shot down a quiet modern hospital corridor at night, soft blue-white fluorescent light, a few occupied patient rooms with doors ajar, a lone nurse walking away in the distance, shallow depth of field, muted teal and gray palette, realistic, calm and serious tone, no text, no logos, 16:9, 24fps.

### Shot 2: The problem (8 sec)

Medium shot of a hospital case manager in navy scrubs at a cluttered desk, phone held to ear, sticky notes and a printed patient list, a computer screen glowing with a generic spreadsheet, a fax machine beside her, late evening light through blinds, tired but focused expression, documentary realism, handheld subtle movement, no readable text, no logos, 16:9.

### Shot 3: Resolution / outro (6 sec)

Early morning sunrise light streaming into a clean, empty hospital room, freshly made bed, window overlooking a city skyline at dawn, slow push-in, warm golden and soft white tones, hopeful and calm mood, photorealistic, no people, no text, no logos, 16:9.

Put the spoken words and the end card on in edit. Do not bake text into the generated clips. The prompts say no text and no logos so names, phone numbers, and statistics stay accurate in the edit.

## Voiceover

Record it yourself. That is the version hospital buyers trust. If you use ElevenLabs, pick a calm, neutral voice at speaking rate **0.95**.

Music sits under the voice, not beside it: a soft ambient piano from a royalty-free library, at **-24 dB**. No lyrics.

## Exports

Cut three versions from the same recording.

| Cut | Length | Scenes |
| --- | --- | --- |
| Full | 3:00 | All scenes, in order |
| LinkedIn | 60 seconds | Scene 1 (corridor + MHA line), scene 3 (leadership KPIs), scene 5 (patient reasons), scene 7 (approve, then the end card) |
| Teaser | 30 seconds | Scene 1, scene 6 (packet and the three-day-rule citation), end card |

Scene numbers above follow the table from top to bottom: 1 corridor, 2 case manager, 3 leadership, 4 worklist, 5 patient reasons, 6 plan and map, 7 packet and rules, 8 approve, 9 outro. The 60-second note "scenes 1, 3, 5, 7" maps to corridor, leadership, reasons, and packet-or-approve. For LinkedIn, prefer the approve click plus the end card if you only have room for four beats. For the teaser, keep the packet citation so the "it doesn't invent facts" claim is on screen.

## End card

Hold the end card for the last four seconds, over shot 3:

**ClearBed · Free 60-day pilot · Deva Choppa · 617-602-6800**

Type is large, left-aligned or centered, on a dark teal field (#16343d) if the sunrise shot is too bright for white type. No extra slogans.

## Recording checklist

- `DATA_MODE=synthetic` and the corner badge is in frame the whole time you are in the app.
- Show the High filter, then open a Medicare post-acute stay for the map. On this census the two High stays route to home services and guardianship, so they will not draw facilities. A Medium Medicare stay in the 75–84 band with condition ACS or heart failure does. This Synthea seed has no hip-fracture admissions, so read the five reasons that are actually on the card (often age, cancer or heart failure, lives alone, Medicare). If a later population does include a hip fracture, use that stay and the voiceover line as written.
- Facilities on the map are real United States nursing homes from CMS Care Compare, ranked from this Boston hospital. Say that. Do not say their acceptance of dialysis or trach care is reported by CMS; those fields are synthetic. The leadership chart is the national catalog, not only the homes on the map.
- One approval only. Leave the audit trail able to show Sent.
- Export H.264, 1920×1080, 24 or 30 fps, stereo audio.
