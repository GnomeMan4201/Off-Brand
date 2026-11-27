# Intelligence sources: limits and licensing

Off-Brand uses three sources. None of them is a verdict on its own, and none is contacted
for anything except its own published data: no reported site is ever visited.

Checked November 2026. Terms change; re-read them before relying on this page. This is a
maintainer's summary, not legal advice.

## Live check, 2026-11-27 (14:43 UTC)

Fetched once from an isolated machine whose network allowlist contained only these providers' hosts:

| Source | Result |
|---|---|
| urlscan.io search | HTTP 200 without a key. 30 searches per minute (`X-Rate-Limit-*` headers). The phishing query returned results minutes old. **`task.source` is not included in search results** (querying on it works), so the lead falls back to the `phishing` tag, which all 100 sampled results carried. |
| urlscan.io result API | **HTTP 403 "You're not logged in!" without a key** (limit 20/minute). The audit can only re-read scan records (submission source, final host) when `URLSCAN_API_KEY` is set. Searching by scan ID (`_id`) is not allowed on the free plan. |
| OpenPhish | `openphish.com/feed.txt` **redirects to OpenPhish's GitHub repository** (`raw.githubusercontent.com/openphish/public_feed/...`), which the feed client now explicitly allows. 300 URLs. No `Last-Modified` header, so freshness shows as unknown. |
| PhishTank | HTTP 200 **without a key**, via a redirect to `cdn.phishtank.com`. 2.2 MB gzip, 42,479 entries, all `verified: yes` and `online: yes`. Newest verification was 32 minutes old; the oldest still listed dates from 2013. `Last-Modified` is present. |

A single run proves only that the sources answered then. Use the Source Health Check workflow to keep checking.

## urlscan.io

| | |
|---|---|
| Role | Discovery, saved screenshots, scan records (submitter source, tags, final page host). |
| Access | Search API and stored screenshots. Optional `URLSCAN_API_KEY`. |
| Limits | Separate per-minute, per-hour and per-day quotas per action; over-limit requests get HTTP 429. Limits are reported in `X-Rate-Limit-*` headers, which the collector honours. |
| What it can't tell us | The free search fields exclude urlscan's own verdict and brand detection. `task.source` only says which feed submitted the scan, and `task.tags` are set by the submitter. Neither verifies anything, so a urlscan record alone is at most **Suspected**. |
| Licensing | Off-Brand links to public scan pages and shows urlscan's public screenshots (existing behaviour). The [official terms](https://urlscan.io/terms/) reviewed 2026-11-27 restrict republication and systematic data collection. Public availability is not a redistribution license. New public intake, publishing and public audit workflows are disabled unless the owner sets URLSCAN_PUBLIC_REUSE_AUTHORIZED to true after documenting permission. Existing material is unchanged and requires a rights review. |

## PhishTank

| | |
|---|---|
| Role | The only verifying source: community-verified phishing URLs. A verified exact-page match makes a specimen **Source-confirmed**. |
| Access | Hourly dump `online-valid.json.gz`, downloaded once per run and searched locally. Requests carry a descriptive User-Agent, as PhishTank requires. |
| Keys | New PhishTank user registration has been closed since 2020, so new application keys can't be obtained. An existing key can be set as `PHISHTANK_APP_KEY`. |
| Limits | Without a key, the dump allows only a few downloads per day. Every workflow run that checks PhishTank (intake, archive, source health, audit) spends one. The scheduled archive checks once per run; manual workflows require an explicit opt-in and share a concurrency group. This reduces accidental overlap but does not enforce a provider-wide daily quota. Over-limit responses (HTTP 509 or 429) are reported as `rate_limited`, never as "no record". |
| What it can't tell us | The dump lists only phishes that are **verified and still online**. Pages that went offline drop out, so a missing record is not evidence that a page was benign; older specimens are often absent. |
| Licensing | PhishTank's FAQ says the data may be used for commercial and non-commercial purposes. The [official terms](https://phishtank.org/terms.php) reviewed 2026-11-27 distinguish API Data (commercial use permitted) from other Content (restricted reproduction). This is not a blanket redistribution license; confirm intended reuse before republishing provider material. Off-Brand stores only the phish ID, verification flags, timestamps and stated target, and links to PhishTank's own record page. |

## OpenPhish community feed

| | |
|---|---|
| Role | Fallback discovery and a private cross-check (automated classification, no human verification). |
| Access | `https://openphish.com/feed.txt`, plain text. The free Community Feed updates every 12 hours and has a limited number of entries. |
| What it can't tell us | The feed rotates, so a listing can't be linked later. It is an automated classifier: a listing alone is **Suspected**. |
| Licensing | OpenPhish's Terms of Use permit personal use, including independent research. Commercial use needs written consent. Without written permission you may not distribute, display or disclose the information to third parties, or create derivative works from it. The service is provided "as is", with no accuracy guarantee. |
| Off-Brand policy | OpenPhish listings are used only in private triage. They are removed from published evidence, from public triage issues and from the audit report, and the public evidence level is recomputed without them (`evidence.public_view`). |
| Open issue | Public intake no longer uses the direct fallback or knowingly selects OpenPhish-origin scans. The [official terms](https://www.openphish.com/terms.html) reviewed 2026-11-27 restrict third-party disclosure without permission. Unknown upstream origins remain unknown; the public source health workflow does not download OpenPhish. Existing public issues require a separate retrospective review. |

## How the sources combine

See `scripts/evidence.py`. In short:
- **Same upstream counts once.** A urlscan scan submitted from the PhishTank feed is PhishTank's lead, not independent support.
- **Only PhishTank verification confirms.** A verified exact-page match gives Source-confirmed. Corroborated is reserved until independent corroboration is demonstrable. Scheme-only matches are Suspected at most.
- **Same-host records never confirm.** A record for another page on the same host can raise a page only to Suspected.
- **Unavailable sources are reported, never counted.** An unread feed is listed as not checked. When it fails, earlier results are carried forward and labelled.
- **Publishing:** only Corroborated, Source-confirmed and Suspected (shown as "not confirmed") can be published.

Declared origin does not establish independence. The providers may share upstream sources.

Use **Source Health Check** (`source-health.yml`) to confirm that each source actually responds in production before relying on it.
