# OFF-BRAND · The Internet’s Knockoff Aisle

A flea-market critic can tell you where the stitching gives away a fake. Off-Brand gives phishing pages the same treatment. Each review names the brand a page imitates, points out the details that give it away, and rates how convincing the knockoff looks.

## Reading a review

The zine is organized by aisle, from banking to cloud services. Browse an aisle or search by brand, domain, or tell. The critic’s note explains the verdict. The public source lets you check the evidence behind it. Suspect addresses appear as plain text with dots written as `[.]`.

## How a page earns a spot

Off-Brand collects candidates from existing urlscan.io records, with the OpenPhish community feed as a fallback. The collector reads those sources without visiting the reported pages. A candidate enters the editorial queue as a GitHub issue labeled `triage`. A reviewer checks the record, writes up the tells, and applies `approved` to add the review to the collection.

The [review collection](data/reviews.json) is the source for the [static zine](site/). The [editorial queue](../../issues?q=is%3Aissue+is%3Aopen+label%3Atriage) shows what’s waiting for a closer look.
