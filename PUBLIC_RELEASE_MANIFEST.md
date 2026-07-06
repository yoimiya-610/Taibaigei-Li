# Public Release Export

This directory is a clean source export. It intentionally contains no `.git`
directory or commit history, so it can be initialized and linked to a new public
remote repository.

The export excludes local environment files, virtual environments, runtime data,
message/points records, logs, backups, caches, database files and temporary files.
The legacy game plugins are included because the bot loads them at runtime and an
administrator can enable them through the feature switch. They remain disabled by
default; pass `--exclude-disabled-plugins` only for a deliberately reduced build.

Before running the bot, copy `mybot/.env.example` to `mybot/.env` and set your own
API key, administrator IDs and group IDs. Runtime files are ignored by Git through
the included `.gitignore`.
