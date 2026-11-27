# Editorial workbench — Phase 2 baseline

Status: **proposed, not approved for publication**. Audit date: 2026-11-27.
Baseline: main commit [a8ae9f72](https://github.com/GnomeMan4201/Off-Brand/tree/a8ae9f72efda54ce960ec71592b479636a4afbda).
Input: [data/reviews.json](https://github.com/GnomeMan4201/Off-Brand/blob/a8ae9f72efda54ce960ec71592b479636a4afbda/data/reviews.json), SHA-256 `d3f5384f7bc0eb9f3b53c4655d091496bcbbbefdaa4dbad0a61d6ef46ad7595c`.

## Scope and limits

This is a complete **editorial text audit** of all 30 published review objects, their 90 tells, 30 critic notes and associated stored metadata. It is not a new forensic examination of screenshots, live pages, network traffic, ownership or provider verdicts. Screenshots and original result API records were not retrieved. Existing descriptions of screenshots and source findings remain attributed claims awaiting verification. No live target, intelligence feed or private shelf was contacted. No new provider material is redistributed here. The earlier partial audit found four exact PhishTank confirmations and one scheme-only match; do not transfer those aggregate findings to individual entries or change their current evidence level without the specimen-specific record.

This workbench uses only already-published editorial text and stored metadata, not private notes or newly collected data. It is a public repository development document, not a page on the broadcast site. Future source-level evidence, raw records and proposed specimen revisions belong in the authorized private shelf until cleared for publication.

## Baseline inventory

| Metric | Count |
|---|---:|
| Reviews text-audited | 30/30 |
| Tells inspected | 90/90 |
| Critic notes inspected | 30/30 |
| Reviews explicitly titled Suspected phishing | 6 |
| Reviews whose tells attribute Potentially Malicious to urlscan | 24 |
| Reviews with structured evidence blocks | 0 |
| Critic notes using “Nothing says” | 0 |
| Comedic voices in use | 12 |
| Original captures independently re-inspected in this audit | 0 |

The corpus is not superficial across the board. It already distinguishes many observed screens from unobserved next steps, uses varied voices and provides useful address-reading advice. Preserve this. The principal opportunity is to remove certainty that outpaces the record, verify provider attribution, and add specific reader lessons that do not depend on appearance or generic warnings.

## Triage rules

- **P1 (claim correction):** a concrete overstatement, unverified action, identity assumption, misleading technical explanation or apparent contradiction with another field. Resolve before republishing the review.
- **P2 (attribution and depth):** substantially qualified wording but a claim needs source confirmation, terminology refinement, or a more useful lesson. Resolve during normal revision.
- These are editorial priorities, not phishing confidence scores. All rows require source review. A P2 is not an endorsement.
- T1–T3 refer to the ordered tells in the pinned input; J means critic note. Keep the original comedic voice unless the owner decides otherwise. Do not change the existing review order.

## Specimen-by-specimen queue

Each row is a proposed task, not an approved finding about the actual site. The ordinal and brand identify the original review in the pinned file.

| # / review | Priority | Text finding and correction | Evidence to inspect before rewriting |
|---|---|---|---|
| 01 Spotify | P2 | T1/J assert age and lack of affiliation; T2 already limits what the buttons show. Keep the contrast between familiar sign-in choices and the stored address; make credential collection explicitly hypothetical. | Capture, domain-age attribution, official sign-in guidance, button destinations if recorded. |
| 02 AT&T | P1 | T1 says anyone can claim a builder name; T2 uses the categorical claim that real email logins are not built on a shop builder; J calls operators scammers. Use hosting context and visible form as indicators, not proof of control or intent. | Capture fields/footer, hosting relationship, original verdict, official sign-in path. |
| 03 UK Government (GOV.UK) | P2 | T1 broadly equates government services with one suffix. T2/T3 distinguish the eligibility wording from an unseen form; preserve that restraint. Treat the payment offer as an unverified claim, not an established scheme. | Archived offer/registration wording and official eligibility information. |
| 04 Netflix | P1 | T2 says only the address proves something; J asserts Netflix did not commission it. Address mismatch is a clue, not proof of non-affiliation. Preserve the visible language and form, qualify the identity claim. | Capture, hosting metadata, official login guidance and any affiliation evidence. |
| 05 USPS | P1 | T1 claims registration-day timing; T2 assigns intent; T3 calls the destination a thief and equates a printed SSL badge with transport security. A badge proves neither TLS nor operator identity. | Capture, registration-age source, actual recorded TLS state, original verdict. |
| 06 Google | P2 | T1/T2 give a useful distinction between embedded branding and third-party sign-in; T3 already says suspected. Avoid treating a hostname alone as conclusive, and confirm age and community-tag wording. | Capture and official federated sign-in guidance. |
| 07 Afirme | P2 | T2 assumes a copied front door and login purpose; phrase as a hypothesis unless links or comparative captures establish it. Preserve the explicit suspected verdict. | Capture, brand homepage reference, observed navigation, tag/age sources. |
| 08 Phantom | P1 | T2 implies recovery-phrase solicitation beyond the first screen; T3 explicitly says only that screen was captured. Explain the risk of an unexpected wallet setup without claiming a phrase request. | Capture, source tag versus verified record, official wallet recovery guidance. |
| 09 EAAB (Acueducto de Bogotá) | P2 | T2 predicts a card-details step; T3 says payment was not captured. Keep the distinction between account lookup, bulk payment UI and unobserved payment behavior. | Capture, official utility payment channel, original scan classification. |
| 10 BT | P2 | T1 assumes subdomain assignment and J says hosting is free; T2 uses a credential-form metaphor. Preserve the visible fields and footer, verify hosting and avoid claiming submission. | Capture, hosting plan/relationship if relevant, recorded form behavior. |
| 11 Ocean Bank | P1 | T1 asserts bank/cosmetics-company control is absent without ownership evidence. T2/J claim precise holiday timing and current notices. Separate what is visible from ownership and inferred freshness. | Capture date and notice, host attribution, original verdict. |
| 12 Telegram | P1 | T2 moves from an observed phone field to a subsequent login-code step, which T3 says is unseen. Make the second step a generic risk, not this specimen's demonstrated behavior; distinguish legitimate authentication from unsafe sharing. | Capture, official Telegram authentication guidance, any recorded later screen. |
| 13 Ledger | P2 | T1 cites precise domain age and T2 attributes copy to Ledger. J treats correlated tags as agreement. Verify wording/age and explain that multiple submitter labels are not independent verification. | Capture, original labels, official material for comparison. |
| 14 Navy Federal Credit Union | P1 | T1 calls a label a misspelling and attributes control; T2 infers selective targeting from a redirect. The current qualification is useful but the observed hop does not establish filtering. | Archived redirect chain, original scan fields, capture. |
| 15 Grupo Aval | P2 | T1 assumes hosting tenancy; T2 makes a general risk claim about bill payments; J asserts absence of support. Retain the observed menu and suspected verdict; omit unsupported customer-service claims. | Capture, hosting context, navigation and source tags. |
| 16 Coinbase | P2 | T1 gives a precise age; T2 correctly distinguishes signup offer from form transmission. T3 claims tracking loaded; verify the recorded request and explain that analytics alone does not prove phishing. | Capture, age attribution, archived network record, original verdict. |
| 17 Trezor (storefront) | P1 | T2 infers selective delivery from a tokenized hop and J dramatizes a checkpoint. Keep the archived redirect observation separate from unknown decision logic. No purchase was recorded per T3. | Archived redirect chain, capture, official wallet management guidance. |
| 18 Trezor (documentation) | P2 | T2 says updates never arrive through a hosted document page; T3 explicitly leaves the external destination unknown. Distinguish trusted download origin from appearance and avoid categorical delivery claims without official documentation. | Capture, link metadata if recorded, official update guidance. |
| 19 Trezor (setup guide) | P2 | T1 is a useful cross-brand inconsistency; T2/J assume a free hosting plan or lack of domain ownership. Keep the contradiction, verify the footer, and leave the download behavior unconfirmed. | Capture title/body/footer, hosting context, recorded download/link metadata. |
| 20 D'CENT | P1 | T1 treats conflicting brands as proof neither built the page; T2 implies recovery-phrase entry while T3 says none was shown. Keep both as indicators and explicitly label the unobserved action. | Capture, recorded link, tag attribution, official recovery guidance. |
| 21 Microsoft (security check) | P1 | T1 asserts intended misspelling; T2 asserts psychological conditioning from a broken widget; J calls it a login page while T3 says no sign-in was recorded. Describe the visible check, then qualify inferred purpose. | Capture, original host and verdict, any recorded later page. |
| 22 Adobe Document Cloud | P1 | T2 says real verification codes arrive by text/email and are typed manually, which is overbroad. Keep the unusual copy/paste instruction as an indicator, not a confirmed exploit or universal rule. | Capture, exact code/continue instructions, destination if recorded, official verification guidance. |
| 23 Microsoft (terms notice) | P2 | T2/T3 appropriately distinguish the claimed terms update and unseen next step; J asserts why it works without user evidence. Explain plausible authority cues without asserting a measured effect. | Capture text/translation, original redirect and verdict, official account guidance. |
| 24 Apple iCloud | P1 | T2 asserts the check is fake and buys time before the next screen, which is not recorded. Preserve the visible robot-check and stale footer as indicators, not proof of behavior or identity. | Capture, original verdict, any archived subsequent state. |
| 25 Axelar | P2 | T1 says visual confusion is the entire technique; T2 calls the bonus bait. Qualify the inferred persuasion mechanism; T3 correctly states the wallet signing request is unseen. | Capture, official governance announcement if available, source-tag attribution. |
| 26 Telcel | P1 | J says the page shoots for a phone number, but T3 says the capture ends before the button's collection is known. Remove that specific action unless the archived record supports it. Preserve the visible expiration prompt and urgency lesson. | Capture, button destination or recorded subsequent screen, official rewards guidance. |
| 27 Xaman | P1 | T2 implies wallet asset authorization from a claim button, while T3 explicitly says no signing request was observed. Describe unexpected wallet-connection risk, not an observed transaction or theft. | Capture, original tag/verdict, recorded wallet prompt if available. |
| 28 Moonshot | P2 | T1 assumes hosting access is unrestricted; T2 correctly distinguishes displayed activity from its provenance. J's precise activity age needs capture confirmation. Keep the social-proof analysis as a hypothesis. | Capture and displayed timestamps, hosting context, any recorded prompt. |
| 29 Allegro Lokalnie | P2 | T1/T2 explain address hierarchy and genuine outbound links; T3 distinguishes no observed submitted password. Verify the link and verdict attribution, and do not treat a scheme-only source match as exact confirmation. | Original capture/scan, recorded outbound links, scheme-aware provider match. |
| 30 Ledger Live | P2 | T2 is a strong example of the distinction between ordinary chat software, possible social engineering and unknown transcript/operator. T1's redirect claim and T3's verdict attribution need verification. Preserve the bounded inference and joke. | Archived redirect/network evidence, capture, source verdict. |

## Revision template (private until approved)

For each review, keep a claim ledger outside the public production JSON while drafting:

| Field | Required content |
|---|---|
| Review identity | Existing specimen ID and pinned revision; no live target links |
| Observed | Exact screen or archived-record claim, pointer, capture time |
| Source-attributed | Provider, record type, date, match class, confidence, availability |
| Inferred | One clearly qualified interpretation; plausible alternative |
| Unknown | Missing destination, submission, ownership or subsequent state |
| Reader lesson | One practical protective check that follows from observed facts |
| Satire | One original joke tied to a verified detail, not inferred criminal intent |
| Disposition | Keep, qualify, remove, defer, or request evidence; owner approval |
| Correction note | Old/new claim, reason, date, reviewer, source pointer |

Recommended editorial shape for What to Notice: (1) **address/identity**, (2) **visible request or authority cue**, (3) **limits and practical takeaway**. Use the existing voice-specific headings. The public Evidence Locker remains the sole structured source-confidence presentation; editorial prose cannot raise that level.

## Release gates

1. Verify each factual statement in T1–T3 and J against accessible, authorized archival evidence; mark unavailable rather than guessing.
2. Use “appears,” “could,” or “consistent with” for unobserved behavior. An archived screenshot does not establish where a form sends data, whether a login succeeds, or whether credentials or funds were stolen.
3. Verify provider terminology. A submitter tag, automated verdict and human-verified exact match are different evidence. Domain age, platform use, TLS and foreign-language details are not verdicts.
4. Verify official-service advice against authoritative documentation when specific routes or product behaviors are claimed.
5. Do not introduce raw provider data, private screenshots, or restricted source information into this public PR. Authorization for reuse remains required.
6. Keep the site's exact tagline and voice rotation; do not grade jokes by how strongly they accuse. Preserve owner approval. Publish in small reviewed batches only after evidence and rights gates are satisfied.
7. Retain a dated correction history; never silently turn an unverified historical review into a confirmed case.

Suggested first batch: P1 reviews 02, 05, 20, 22, 26. These represent five distinct failure modes: categorical hosting claims, misleading security badges, conflicting brands, overbroad authentication advice, and an unsupported next-step claim. All are blocked on evidence review; none is rewritten here.
