# Off-Brand voice guide

Off-Brand reviews phishing pages the way a sharp, slightly mean critic reviews cheap knockoffs. The joke is how we get people in the door; the lesson is the reason we're here.

## The rules

1. **Every tell is a joke plus a lesson.** If you removed the joke, a reader should still learn how to spot this trick next time. If you removed the lesson, the tell gets cut.
2. **Punch at the scammer, never the victim.** Being fooled is normal: these pages are built to fool people. Don't mock anyone who fell for one, and don't mock the brand being impersonated.
3. **The facts stay real.** Every claim in a joke has to be true and checkable from the public record. If you can't verify it, it doesn't go in, however funny it is.
4. **No jokes about nationality, language or culture.** "Login in Polish" is a fact. Making fun of Polish is off-limits.
5. **One strong line beats three okay ones.** Cut the second joke in a sentence.
6. **Safety advice is never a punchline.** Advice like "never share your recovery phrase" is stated plainly. Only the setup around it is funny.

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
