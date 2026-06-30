# Public Release Manifest

This repository is a clean public source export of the Li Taibaigei bot.

## What is included

- Source code under `mybot/`
- Tests, CI workflow, and deployment scripts
- Legacy game plugins that are still runtime-loadable but disabled by default
- A `.gitignore` suitable for public development and deployment

## What is intentionally excluded

- Real `.env` files and any deployment secrets
- Runtime data under `mybot/data/`
- Logs under `mybot/logs/`
- Backup archives under `backups/`
- Virtual environments, caches, local adapter directories, and database files
- Original Git history from the private/export source

## Operational notes

- Copy `mybot/.env.example` to `mybot/.env` and fill in your own values before running.
- Runtime files stay local to the deployment machine and should not be committed back to Git.
- Legacy game plugins are kept because the bot loader still imports them; administrators can enable them through feature flags when needed.
- Use `--exclude-disabled-plugins` only when deliberately preparing a reduced public build.

## Related docs

- [README.md](README.md): repository overview and quick start
- [mybot/README.md](mybot/README.md): bot runtime and development entry
- [docs/runtime-state-migration.md](docs/runtime-state-migration.md): migration steps for older deployments
