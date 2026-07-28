# Public Baseline Manifest

## Baseline identity

- Public baseline: **v0.7.0.1**
- Product/package version: **v0.7.0**
- Target repository: `yoimiya-610/Taibaigei-Li`
- Base branch: latest `origin/main`
- License selected for this repository: MIT
- Formal GitHub Release: not created

This baseline was applied on top of the public repository's existing history. Its `.git` directory, CI history, issues, pull requests, and collaboration history were not replaced or rebuilt.

## Candidate verification

The only imported code source was the export-v2-validated candidate. Before import:

- 116 files were inventoried, including hidden files and generated artifacts.
- Candidate metadata reported version `0.3.1`; public package metadata was intentionally normalized to `0.7.0`.
- 93 selected files under `mybot/` were copied individually.
- SHA-256 was computed for every selected source and destination file immediately after copy: **93 matched, 0 mismatched**.
- Secret-like assignments, private keys, credentials, private host literals, and private default IDs were scanned.
- The public environment template had empty secret, administrator, group, and access-token values.
- `BLACKLIST_WORDS` was empty.

The candidate documentation contained deployment-specific absolute paths and obsolete export-repository assumptions. Those files were reviewed but rewritten for the public-upstream model instead of copied verbatim.

## Excluded candidate material

The following material was deliberately not imported:

- `backups/` and runtime directory placeholders.
- Generated `mybot.egg-info/` metadata.
- Local release-note artifacts.
- Runtime data, logs, databases, caches, archives, and local environment files.
- The old private-to-public export tool and its export-only test.
- `napcat.sh`.

The excluded `napcat.sh` was 50,453 bytes with SHA-256
`610CC4582004EF9204937A16FAB103EAE0D299E959BC9ED4E676D3A451CFD509`.
It did not contain a copyright or license notice establishing redistribution rights, so it is not republished. Public documentation links to the official NapCat installation and integration guides instead.

## Public-tree controls

`tools/check_public_tree.py` checks tracked and unignored files for:

- runtime data and forbidden directories;
- environment files, credentials, private keys, and secret-like assignments;
- private administrator/group defaults and non-loopback host literals;
- personal absolute paths, private infrastructure labels, and forbidden remotes;
- databases, logs, backups, local OneBot configuration, and redistributed `napcat.sh`;
- empty public defaults, an empty source blacklist, required public documents, and synchronized version metadata.

CI runs this check together with locked dependency sync, compilation, the full test suite, deployment-script syntax validation, and an application-entry smoke test.
