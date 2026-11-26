# OFF-BRAND — The Internet's Knockoff Aisle

A static zine that reviews real phishing pages like cheap flea-market knockoffs.
Zero servers, zero live phishing links, phone-only publishing via GitHub Issues + GitHub Actions.

## Phone-Only Setup (5 Minutes)
1. Create a new public GitHub repo and upload these files.
2. In **Settings -> Pages**, set **Source** to **GitHub Actions**.
3. Create two Issue labels in **Issues -> Labels**: `triage` and `approved`.
4. (Optional but recommended) Sign up for a free **urlscan.io** account, grab an API key, and add it as `URLSCAN_API_KEY` in **Settings -> Secrets and variables -> Actions**.
5. Run **Fetch Phishing Candidates** from the **Actions** tab (or wait for the daily schedule).
6. Open the **GitHub Mobile app**, tap a `triage` issue, inspect the safe `urlscan.io` public report, reply with the short `key: value` review block, and add the `approved` label. GitHub Actions publishes it automatically.

## Security Guarantees
- Every URL and domain is defanged (`hxxps://...`, `[.]`).
- All scanned strings are sanitized (`scripts/sanitize.py`) and rendered via `.textContent` only (never `innerHTML`).
- Strict Content Security Policy in `site/index.html`.
- Public record links are allowlisted to `urlscan.io`, `openphish.com`, and `phishtank.net`.
