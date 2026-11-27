# Maintaining Off-Brand

## Configuration

- Configure GitHub Pages to use GitHub Actions.
- Set the optional `URLSCAN_API_KEY` repository secret for authenticated public scan collection.
- Ensure the `triage` and `approved` issue labels exist. The ingestion and publication workflows require the permissions declared in their workflow files.

## Review and publication

Manual ingestion (`ingest.yml`) searches up to 25 candidates per source and stages at most three fresh candidates per run. If urlscan yields no fresh candidates, it uses the OpenPhish community feed. Feed-only records may lack a screenshot or scan details. Source labels are leads rather than verified verdicts.

Inspect the record and screenshot before approving a review. Use the key/value fields supplied in the triage issue:

```
brand: <Target brand>
aisle: <Category>
knockoff_label: <Satirical product name>
verdict: <Satirical verdict>
rating: <Rating out of 10>
sketchy_segment: <Exact defanged URL segment>
tells: <Observation> | <Observation>
critic_note: <Review>
voice: critic
edge: 2
```

The [editorial guide](../VOICE.md) and [voice roster](../data/voices.json) define the available voices and edge levels. Adding the `approved` label triggers validation and publication through `publish.yml`. Records that do not meet the editorial standard should not be approved; the published exclusion log is stored in `data/reviews.json` under `rejected_log`.

## Private specimen archive

Create a separate private repository with a default `main` branch and the `triage` and `approved` labels. Configure `SHELF_REPO` as the repository variable (owner/name) and `SHELF_TOKEN` as a secret restricted to that repository, with Contents and Issues read/write access. The archive workflows check that the shelf is private.

- `archive.yml`: collects existing urlscan records and screenshots. Manual runs default to dry-run; scheduled collection requires `ARCHIVE_SCHEDULE_ENABLED=true`. The default archive storage cap is 500 MB. Collection retains resume state.
- `write-specimen.yml`: creates or reuses a private draft issue for a selected specimen.
- `publish-shelf.yml`: publishes an approved private specimen using the same validation pipeline.
- The archive's Markdown index provides Unwritten, Drafted, Published and All views, with thumbnails and links to individual records. Screenshot observations are recorded in the private shelf's `data/archive_inspections.json` as attributed observations with image pointers.

The private archive, unapproved screenshots, draft notes and collection state must not be committed to the public repository.

## Commercials

The manifest at `site/commercials/manifest.json` determines CH 00 listings and the rotation. Automatic breaks occur after 4–7 channel changes, start muted, respect reduced motion and can be disabled. A failed video returns the viewer to the program.

Store H.264/AAC MP4s and JPEG, PNG or WebP posters in `site/commercials/`, with lowercase alphanumeric/hyphen filenames. Keep videos below 25 MB. Use fast-start and remove unnecessary container metadata. Add a manifest entry with `id`, `title`, `runtime_seconds`, `src`, `poster` and `description`. Use `captions: "burned-in"` only for verified embedded captions, or provide a `captions_vtt` path for WebVTT. Set `enabled: false` to disable a commercial without deleting its assets.

## Local checks

```sh
mkdir -p _site/data
cp -r site/* _site/
cp data/reviews.json _site/data/
python3 -m http.server -d _site 8000
```

```sh
python3 -m pytest -q tests
```

The suite includes Node.js checks when Node is installed, codec/runtime checks when ffprobe is installed, and browser checks when Playwright and a supported browser are available.
