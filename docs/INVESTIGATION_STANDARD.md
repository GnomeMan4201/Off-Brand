# Off-Brand investigation standard

**Editorial protocol v1 — proposed for maintainer adoption.**

The joke gets a reader's attention; the investigation earns their trust. Teach readers to question convincing pages, not merely recognize bad design. This protocol supplements [VOICE.md](../VOICE.md), [SOURCES.md](SOURCES.md) and [MAINTAINING.md](MAINTAINING.md). It is a human review procedure, not a replacement for the authenticated collection, evidence classification, provider reuse authorization or owner-selected publication gates.

## Six questions for every investigation

Answer each in a private research note. If the record cannot answer a question, document what is unknown and why. Do not manufacture a finding.

| Question | Required substance |
|---|---|
| What is visible? | Specific text, controls, images and captured state; identify the capture reference and date. |
| What does the page claim? | Attribute the claimed identity, request, offer, warning or service to the page. |
| How might it persuade? | Identify a specific urgency, authority, familiarity, incentive, loss-of-access or social-proof cue. Explain its plausible effect without claiming actual intent or success. |
| What supports suspicion? | Distinguish the stored address, source metadata, original scan record and permitted independent verification. State exact versus related match scope and evidence level. |
| What remains unknown? | Name the consequential missing behavior or record, such as submission, destination, ownership, later screen, original classification or current status. |
| What should the reader learn? | A practical, transferable defensive action. Do not require visiting the reported destination. |

These questions are research requirements, not six mandatory UI sections. Retain the existing broadcast format, assigned voice and edge. Condense the investigation into two to four distinct What to Notice tells. Each should teach something even without its joke.

## Claim-by-claim evidence ledger

Complete one private ledger row per material factual assertion, including those embedded in the title, label, verdict, critic note or captions.

| Claim ID | Proposed wording | Basis | Exact reference | Limit / alternative | Decision |
|---|---|---|---|---|---|
| [ID] | [claim] | [basis] | [reference] | [limit] | [retain / qualify / remove / hold] |

Use these bases:

- **Observed:** visible in the archived capture. Specify where. A printed claim proves only that the page displays it.
- **Stored:** existing editorial or provider metadata. Identify its origin and whether the original record was re-read; do not imply that metadata is visible in the capture.
- **Source-attributed:** a named provider record, with date, match type and limitations. Attribution is not independent corroboration.
- **Inferred:** a plausible interpretation, stated conditionally. Consider material alternative explanations.
- **Unknown:** unavailable, not checked or not established. Never turn uncertainty into an observed fact.

Record a capture SHA-256 if authorized bytes were obtained. It identifies bytes, not the truth of the depicted content. Never reconstruct a missing screenshot as evidence. Do not visit reported targets, submit forms, connect wallets, execute downloads or test a live scam.

## Investigate the mechanism, not the appearance

- **Identity and address:** distinguish hostname, subdomain, path and claimed brand. Hosting platforms, domain age and logos alone do not establish ownership or maliciousness. Do not infer registrable-domain boundaries from a fixed count of labels.
- **Persuasion:** describe the actual cue and plausible effect; do not assert the operator's intent or that a reader was deceived.
- **Requested action:** describe visible fields, buttons and requests precisely. A button does not establish its destination; a field does not establish collection.
- **Recorded behavior:** attribute redirects, network requests, tracking, form destinations or scripts to specific authorized records actually inspected. A recorded event does not by itself establish its purpose.
- **Verification:** distinguish capture time, source health, exact matches, related matches and current availability. An unavailable record is not a negative finding.

Do not call a challenge fake, claim a wallet signature or transfer occurred, or allege theft without evidence of that behavior. Avoid categorical claims about what legitimate services never do. Verify specific advice about official-service behavior through appropriate sources. Do not impose a mechanism the specimen does not exhibit.

## Evidence and editorial disposition

Use the existing evidence engine. A good joke or detailed investigation cannot raise an evidence level. Preserve Corroborated, Source-confirmed, Suspected (not confirmed), Unverified, Disputed and legacy Not yet rated. Under current source rules, Corroborated is not awarded; same-upstream records count once; same-host and scheme-only matches do not establish exact confirmation. Unverified and Disputed new specimens stay off air. Suspected specimens require the existing not-confirmed label and cautious wording.

| Disposition | Meaning |
|---|---|
| Ready for owner review | Six questions addressed, claims supported or qualified, public-safe copy prepared, applicable reuse and technical prerequisites documented. Not publication approval. |
| Revise | A claim, attribution, lesson, joke or length needs correction. |
| Hold | Source access, evidence, reuse permission, privacy or individual approval remains unresolved. |
| Exclude | Existing safety or editorial criteria justify withholding; record the reason without restricted material. |

For historical corrections, pin the public baseline and draft, compare old and proposed wording, record evidence, limitations and date, obtain individual approval, and use a separately reviewed release. Never silently upgrade a rating or infer an individual's classification from aggregate counts.

## Broadcast copy

Preserve the voice rules: punch at deception, not victims, nationalities, cultures or impersonated brands. Avoid repetitive joke openings and factual claims disguised as satire. Safety advice stays plain. Across the tells, explain a persuasive cue, technical basis, consequential limit and transferable lesson. Put source-level detail in the Evidence Locker.

The publisher currently caps each tell at 280 characters, critic_note at 500, knockoff_label at 90, verdict at 60, rating at 16 and sketchy_segment at 120. VOICE.md sets additional shorter editorial targets. Check the exact sanitized text before approval; never let truncation remove a negation, attribution or uncertainty. Keep deeper notes private rather than pasting them into the publication comment.

## Reusable private review checklist

- [ ] Pin specimen ID, scan reference, capture date, historical baseline and draft revision.
- [ ] Record capture availability and actual inspection; identify missing assets honestly.
- [ ] Answer all six questions and reconcile material claims in the ledger.
- [ ] Verify match scope, source status and assessment; distinguish unavailable from no record.
- [ ] Check brand, address, behavioral and official-service assertions; preserve material uncertainty.
- [ ] Verify factual premises of jokes, voice and edge; remove redundant tells and victim-blaming.
- [ ] Check public text after sanitization against field limits, privacy and defanging rules.
- [ ] Document applicable reuse authorization; hold if not established.
- [ ] Record correction or exclusion reasons where applicable.
- [ ] Obtain individual owner approval through the existing release process; record its reference.

Complete the [private worksheet](INVESTIGATION_WORKSHEET.md) before preparing the existing single-line key/value review block described in MAINTAINING.md. Do not add worksheet fields or prose to the selected publication comment. The checklist is a human editorial requirement; the software currently enforces structural and provenance rules, not the truth of each sentence or completion of the checklist.

No new publication, source permission, confidence upgrade, or historical compliance is implied by adoption of this protocol.
