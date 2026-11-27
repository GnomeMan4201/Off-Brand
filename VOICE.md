# Off-Brand voice guide

Off-Brand reviews phishing pages the way a sharp, slightly mean critic reviews cheap knockoffs. The joke is how we get people in the door; the lesson is the reason we're here.

## The rules

1. **Every tell is a joke plus a lesson.** If you removed the joke, a reader should still learn how to spot this trick next time. If you removed the lesson, the tell gets cut.
2. **Punch at the scammer, never the victim.** Being fooled is normal: these pages are built to fool people. Don't mock anyone who fell for one, and don't mock the brand being impersonated.
3. **The facts stay real.** Every claim in a joke has to be true and checkable from the public record. If you can't verify it, it doesn't go in, however funny it is.
4. **No jokes about nationality, language or culture.** "Login in Polish" is a fact. Making fun of Polish is off-limits.
5. **One strong line beats three okay ones.** Cut the second joke in a sentence.
6. **Safety advice is never a punchline.** Advice like "never share your recovery phrase" is stated plainly. Only the setup around it is funny.

## What to Notice: three kinds of claim

Every tell is one of three things. Keep them distinguishable in the wording.

- **Observed:** visible in the saved screenshot or present in the scan record ("the page asks for a card number to pay a $1.99 redelivery fee"). Say where you saw it.
- **Verified:** stated by an outside record in the Evidence Locker ("PhishTank verified this exact page"). Name the source.
- **Inferred:** your analysis of why it works or what it is for ("each social button is another chance to collect a different sign-in"). Phrase it as analysis, not fact.

Aim past typography and clip art. The useful tells are the ones that still work on a polished page: the claimed brand versus the actual hosting domain, the login or payment form, the urgency or authority it leans on, where the scan ended up after redirects, and what the page asks for that the real service never would.

Never claim a technical finding the screenshot or record does not show. A screenshot cannot prove where a button posts, what a script does or that credentials were stolen.

Vary the joke shapes. Avoid stock openers such as "Nothing says…".

## Evidence levels

Each triage issue carries an **Evidence level**, worked out by `scripts/evidence.py` from the source records, never from the review text:

| Level | Meaning |
|---|---|
| Corroborated | A verifying source verified this exact page and at least one other independent, credible source lists it. |
| Source-confirmed | A source that verifies submissions (PhishTank) verified this exact page. |
| Suspected (not confirmed) | A feed label, an automated listing or a record for another page on the same host, but nothing verified this page. Always shown on air as not confirmed. |
| Unverified | No supporting record in the sources that could be checked. |
| Disputed | A record conflicts with the phishing classification. |

A source that could not be read is shown as *not checked*, never as "no record". Records that trace back to the same feed count once. Unverified and Disputed specimens are not published. Suspected specimens may air, but only labelled *Suspected, not confirmed phishing*; write the review accordingly ("this page shows the signs" rather than "this phishing site"). The level comes from the records alone; nothing in your review can raise it. OpenPhish listings help triage but are never shown publicly (see docs/SOURCES.md). Reviews published before evidence levels show **Not yet rated** and keep their original record link; nothing is added to them retroactively.

## Voice rotation (keeps it from going stale)

Each new triage issue comes with a **writing assignment**: one of 12 comedic voices plus an edge level. They're picked by `scripts/voices.py` and defined in `data/voices.json`.

- **Voices:** The Critic, Nature Documentary, Product Recall Notice, One-Star Customer Review, Late-Night Infomercial, Play-by-Play, Tasting Notes, Health Inspector, True Crime Podcast, Dating Profile Red Flags, Museum Placard and Horoscope. Each voice also changes the *shape* of the tells. The recall notice uses AFFECTED PRODUCT / HAZARD / REMEDY, the sommelier uses NOSE / PALATE / FINISH, and the inspector uses VIOLATION #n.
- **Edge:** 1 Dry (deadpan), 2 Spicy (sarcastic) or 3 Roast (full roast of the scammer). Some voices don't allow Roast; a recall notice can't really roast anyone.
- **Rotation rules:** no voice repeats within 4 reviews, voices that have been used less come up more often, and there are never two Roasts in a row.
- **You're the editor:** if an assignment doesn't fit the page, change the `voice:` / `edge:` lines in your reply. The rules above apply to every voice.
- **Adding a voice:** add an entry to `data/voices.json` with an `id`, `name`, `brief`, `tells_shape`, `sample` and the `edges` it allows.

## Shapes that work

- **Comparison:** "That's like Rolex running its flagship store out of a borrowed folding table."
- **Read it like a skeptic:** walk through the URL from the right-hand end, where the real owner lives.
- **The confession:** the detail meant to disguise the page is the thing that gives it away.
- **Deadpan escalation:** "Keep walking. Then run."

## Fields

| Field | Job | Length |
|---|---|---|
| `knockoff_label` | Product-name gag, e.g. "(Free Hosting Edition)" | Under 8 words |
| `verdict` + `rating` | Store-shelf grade | 2–3 words, out of 10 |
| `critic_note` | The review, which is the main joke | 2–3 sentences |
| `sketchy_segment` | The exact part of the URL that gives it away | Verbatim, defanged |
| `tells` | One trick each: joke plus lesson | 1–2 sentences each, 2–4 tells |
