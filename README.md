# OFF-BRAND

**The internet’s knockoff aisle. Real phishing sites reviewed by me GnomeMan4201**

A late-night television station for the internet's questionable merchandise. Off-Brand is a screenshot comedy zine about phishing, impersonation and the warning signs hiding in plain sight.

**[Watch Off-Brand After Dark](https://gnomeman4201.github.io/Off-Brand/)**

## The broadcast

- **Tonight's lineup:** browse reviews by channel, brand, domain or aisle.
- **What to notice:** a fact file and practical observations tied to each public scan record.
- **CH 00 — Off-Brand Originals:** fictional commercials, available on demand and during optional commercial breaks.
- **Held back at review:** records excluded from publication and the reasons for those decisions.
- **Phishing field guide:** practical advice for recognizing, verifying and reporting suspicious requests.

## Editorial standards

The specimens are real captured pages, not reconstructed scam websites. Each published review links to its public record. Source classifications are attributed to the source; a suspicious or reported page is not automatically confirmed phishing. A screenshot documents one moment and cannot establish everything that happened before or after capture.

The ratings and verdicts are satirical editorial judgments, not measured risk scores. The comedy targets deceptive design, not victims, nationalities or the brands being impersonated. Missing evidence is identified as missing rather than filled in with guesses.

Reviews are subject to editorial approval. Creative production may be AI-assisted; fictional commercials and their imagery are separate from the public scan evidence. See the [editorial guide](VOICE.md) for review standards.

## Safety and privacy

- Suspect addresses are defanged and are not clickable.
- Collection reads public scan records and feeds rather than visiting suspect sites.
- Captured text is treated as untrusted data and displayed as plain text.
- The site uses a restrictive content security policy. Screenshots are served from urlscan.io; commercial media, fonts and sounds are served locally.
- A source may remove a public screenshot or record at any time. Its scan date is not proof that the suspect site is still active.
- Unapproved archived specimens and draft reviews are maintained separately in a private repository.

## Repository

Off-Brand is a static site published using GitHub Pages. The collection, review, approval and publication workflows run through GitHub Actions.

| Path | Purpose |
| --- | --- |
| `site/` | Broadcast interface, player, commercial assets and local resources |
| `data/reviews.json` | Published reviews and excluded-record log |
| `data/voices.json` | Editorial voice and tone definitions |
| `data/seen.json` | Candidate deduplication |
| `scripts/` | Collection, sanitization, archive and publication tooling |
| `.github/workflows/` | Collection, approval and deployment workflows |
| `tests/` | Automated regression tests |

See [maintenance documentation](docs/MAINTAINING.md) for configuration, review publication, commercial management and local testing.

## Credits

Public scan records and screenshots: [urlscan.io](https://urlscan.io). Candidate-feed fallback: [OpenPhish](https://openphish.com). The currently published review collection uses public urlscan records.

[Broadcast sound sources](site/sounds/SOURCES.md) · [Font licenses](site/fonts/)

Off-Brand is a [badBANANA Research Collective](https://badbananaresearch.com) project.
