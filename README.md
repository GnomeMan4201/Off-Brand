# OFF-BRAND
### The internet's knockoff aisle.

Somewhere out there, a guy registered `allegrolokalnie.aukcja758487593.top` and thought, *nailed it.*

Off-Brand is where his work gets the review it deserves. Every page in the aisle is a **real phishing page**, pulled from a public scan record, screenshotted, and reviewed by hand by me, GnomeMan4201. Then it's mocked, thoroughly and accurately, in a rotating cast of comedic voices, until you can spot the next one from across the room.

It's a gallery, a zine and a free lesson in not getting robbed. Mostly it's a roast.

**👉 [Browse the aisle](https://gnomeman4201.github.io/Off-Brand/)**

---

## The one rule: nothing fake

Every listing traces back to a public record you can check yourself. No invented examples, no made-up stats, no "artist's impression" of a scam. If a scan didn't record something, the page says **"Not recorded in public scan"**. That's an honest blank, not a guess.

The jokes follow the same rule: **every punchline has to be true.**

## House safety rules

Off-Brand stocks counterfeits. It doesn't sell them.

- **Zero live links.** Every suspect address is defanged: `hxxps://`, with dots written as `[.]`. You can't click into a phish from here.
- **We never touch the scam sites.** The robots read existing public scan records and nothing else.
- **Scanned text is treated as hostile.** Page titles, URLs and anything else that came off a phishing page is shown as plain text and never rendered as HTML.
- **Screenshots come from urlscan.io only,** with no referrer sent and a strict content security policy.
- **A human approves every listing.** Robots mislabel things. A real person reads each one before it goes on the shelf, and the ones that get pulled show up in the **Pulled from the shelf** log on the site.

---

## How a knockoff gets on the shelf

```
 urlscan.io public scans (only ones with an archived screenshot)
          │
          ▼
  🤖 ingest.yml     twice a day, sharing a cap of 10 new candidates per day
          │         (backfill.yml: a manual one-off of up to 30 from the past week)
          │         opens a `triage` issue for each, with a 🎭 writing assignment
          ▼
  🤖 draft          a small open-weight model running on the Actions runner
          │         posts a DRAFT review comment (no API key, nothing sent elsewhere)
          ▼
  🧑 you            check the draft against the screenshot, fix it,
          │         fill every placeholder, add the `approved` label
          ▼
  🤖 publish.yml    validates your review, adds it to data/reviews.json,
          │         closes the issue
          ▼
  🤖 deploy.yml     republishes the site to GitHub Pages
```

The whole thing runs on GitHub with free tiers only: no server, no database, no babysitting. You can run the entire operation from a phone.

---

## Setup

You'll need a GitHub account and a free urlscan.io account. Allow about ten minutes.

1. **Get the repo.** Fork or clone it into your account.
2. **Get a urlscan API key.** Sign up free at [urlscan.io](https://urlscan.io), then go to your profile → API keys → create one.
3. **Store the key as a secret.** In the repo, go to **Settings → Secrets and variables → Actions → New repository secret**. Name it `URLSCAN_API_KEY` and paste the key.
4. **Turn on Pages.** Go to **Settings → Pages → Build and deployment → Source: GitHub Actions**.
5. **Create the two labels.** In **Issues → Labels**, make sure `triage` and `approved` both exist. The robots look for those exact names.
6. **Let the bots work.** Go to **Settings → Actions → General → Workflow permissions** and select **Read and write permissions**.
7. **Check the drafting speed.** Go to **Actions → Draft Benchmark → Run workflow**. It times three drafts on the runner and puts a sample in the run summary.
8. **Stock the shelf.** Go to **Actions → Fetch Phishing Candidates for Phone Triage → Run workflow**. Triage issues appear, each followed by a draft comment a minute or two later. For a fuller launch, run **Backfill Candidates (manual)** once.

After that, it restocks itself every morning.

---

## Writing a review

Open a `triage` issue. Each one contains:

- **The record:** scan ID, defanged URL, IP, scan time and a link to the public scan. Open that link and look at the screenshot before you judge anything.
- **Auto-detected observations:** literal facts about the address, like the domain ending, free hosting or how many levels the hostname has. They don't say which brand is being imitated; the screenshot does.
- **🎭 Your writing assignment:** the comedic voice and edge level for this review (see below).
- **A draft review** in the first comment, headed **DRAFT — verify against screenshot**.

The draft looks like this:

```review
brand: Needs editor verification
aisle: Needs editor verification
knockoff_label: Needs editor verification
verdict: Needs editor verification
rating: Needs editor verification
sketchy_segment: Needs editor verification
tells: Domain ends in .top, ... | URL path contains 'logowanie'
critic_note: (a joke in the assigned voice, written by the model from the record only)
voice: critic
edge: 2
```

- **Copied from the record:** `brand` (filled in only when the scan record names one; it's never guessed from the domain) and `tells`, which are literal observations. Turning them into jokes is your job.
- **Written by the model:** only `critic_note`. The model only sees the scan record, never the screenshot, so check every claim it makes.
- **Your job:** replace every `Needs editor verification`, fix anything that's wrong, and punch up the tells. Edit the draft comment in place, or post your revision as a new comment with the same ```review block. Then add the **`approved`** label.

**What gets published is exactly what you approved:**
- It's the review block from the latest comment by you or the drafting bot that was posted *before* you added `approved`. Anything posted later is ignored.
- If that comment is edited *after* you add the label, nothing publishes. Remove the label and add it again.
- If any `Needs editor verification` or `<template>` text is left, nothing publishes. The bot comments with the fields still missing and removes the label.
- Comments from other people never count, so nobody can sneak a review onto the shelf.

- **Aisles in use:** `Banking`, `Crypto & Wallets`, `Marketplace & Retail`, `Cloud & SaaS`. A new aisle name creates a new filter button automatically.
- **Not a phish?** Some "phishing" pages are really corporate phishing-simulation training sites, or something mislabeled. Close the issue without approving it. To show it publicly in the **Pulled from the shelf** log, add an entry to `rejected_log` in `data/reviews.json` with the reason.

---

## The voice rotation 🎭

If every review sounded the same, the site would go stale by the tenth one. So each triage issue arrives with an assigned **voice** and **edge level**, and each voice changes the format of the tells as well as the tone.

| Voice | `voice:` | The bit |
|---|---|---|
| The Critic | `critic` | A snob reviewing a cheap knockoff |
| Nature Documentary | `nature_doc` | A hushed narrator watching a predator in its habitat |
| Product Recall Notice | `recall` | AFFECTED PRODUCT / HAZARD / REMEDY |
| One-Star Customer Review | `one_star` | Ordered a bank, received a lottery number |
| Late-Night Infomercial | `infomercial` | Every flaw sold as a feature. *But wait…* |
| Play-by-Play | `sports` | Calling the scam live, like a game |
| Tasting Notes | `sommelier` | NOSE / PALATE / FINISH |
| Health Inspector | `inspector` | VIOLATION #1, #2… and a letter grade |
| True Crime Podcast | `true_crime` | Clues, revealed with dramatic pauses |
| Dating Profile Red Flags | `dating` | Swipe left |
| Museum Placard | `museum` | *Credential Lure, mixed media, circa Tuesday* |
| Horoscope | `horoscope` | Every prediction is a warning |

| Edge | `edge:` | Means |
|---|---|---|
| Dry | `1` | Deadpan. The joke is how calmly it's said. |
| Spicy | `2` | Sarcastic. The scammer gets mocked openly. |
| Roast | `3` | Full roast of the scammer's craftsmanship. |

**Rotation rules:** no voice repeats within 4 reviews, voices that have been used less come up more often, there are never two Roasts in a row, and some voices don't roast at all (you can't really roast someone in a recall notice). You're the editor: change the `voice:` / `edge:` lines in your reply if the assignment doesn't fit.

**Adding a voice:** add an entry to [`data/voices.json`](data/voices.json) with an `id`, `name`, `brief`, `tells_shape`, `sample` and the `edges` it allows.

### The comedy code

The full guide is in [VOICE.md](VOICE.md). The short version:

1. **Every tell is a joke plus a lesson.** Take the joke out and it should still teach something. Take the lesson out and the tell gets cut.
2. **Punch at the scammer, never the victim.** These pages are built to fool people, and getting fooled is normal. Don't mock the brand being impersonated either.
3. **Every joke has to be true.** If you can't verify it from the record, it doesn't go in.
4. **No jokes about nationality, language or culture.** "Login in Polish" is a fact. Mocking Polish isn't.
5. **Safety advice is never the punchline.** "No real support agent will ever ask for your recovery phrase" is stated plainly.

---

## What's in the box

```
site/                 the zine: index.html, app.js, styles.css (no build step)
data/reviews.json     the shelf: every published review, plus the rejected log
data/voices.json      the comedy roster
data/seen.json        candidates already sent to triage, so they aren't repeated
scripts/ingest.py     fetches candidates from public records (never the sites)
scripts/voices.py     picks each review's voice and edge
scripts/publish_from_issue.py   turns an approved issue into a review
scripts/sanitize.py   defangs URLs and cleans hostile text
tests/                pytest suite
.github/workflows/    ingest, publish and deploy
```

## Running it locally

```sh
# the site
mkdir -p _site/data && cp -r site/* _site/ && cp data/reviews.json _site/data/
python3 -m http.server -d _site 8000      # then open localhost:8000

# the tests
python3 -m pytest -q tests

# fetch candidates yourself
URLSCAN_API_KEY=your-key python3 scripts/ingest.py   # writes data/pending_candidates.json
```

## Known limits (honest ones)

- **Free urlscan keys can't search urlscan's own phishing verdicts.** Those fields are for paid plans, so the robots rely on community tags and scans that came from phishing feeds. That's noisier, which is one reason a human approves everything.
- **At most 10 new candidates per day** across both runs, plus up to 30 per manual backfill. It's a zine, not a firehose. The caps are `DAILY_CAP` and `BACKFILL_CAP` in `scripts/ingest.py`.
- **Only scans with an archived screenshot get in.** OpenPhish feed entries have no screenshot, so the OpenPhish fallback currently adds nothing.
- **Drafts are only as good as a small model.** It runs on the free Actions runner on CPU (`qwen2.5:3b` by default; change `OFFBRAND_MODEL` in the workflows). The first run downloads about 2 GB of model weights, which are cached after that. Drafts are a starting point, never a verdict.
- **Screenshots load from urlscan.** If urlscan removes a scan, its picture goes too, and the card says "No screenshot recorded in public scan."
- **"Scanned" is when urlscan saw the page,** not proof that it's still live. Phishing pages tend to be short-lived.

## Credits

Scan records and screenshots come from [urlscan.io](https://urlscan.io) public scans, with the [OpenPhish](https://openphish.com) community feed as a fallback. Every scammer named on this site did the work of embarrassing themselves; we just wrote it down.

Off-Brand is a [badBANANA Research Collective](https://badbananaresearch.com) project.
