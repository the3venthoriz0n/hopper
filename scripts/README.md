# Deployment Scripts

## sync-env-to-github-secrets.sh

Syncs your local `.env.dev` and `.env.prod` files to GitHub Secrets.

### Prerequisites

1. Install GitHub CLI: https://cli.github.com/
2. Authenticate: `gh auth login`
3. Ensure you're in the repository directory

### Usage

```bash
# Dry run (see what would be set without actually setting)
./scripts/sync-env-to-github-secrets.sh --dry-run

# Actually set the secrets
./scripts/sync-env-to-github-secrets.sh

# Skip confirmation prompt
./scripts/sync-env-to-github-secrets.sh --skip-confirm
```

### What it does

1. Reads `.env.prod` and adds `PROD_` prefix to all secrets
2. Reads `.env.dev` and adds `DEV_` prefix to all secrets
3. Skips:
   - Empty lines
   - Comments (lines starting with #)
   - Variables with empty values
   - Variables with substitution (e.g., `${VAR}`)

### Example

If your `.env.prod` contains:
```
DOMAIN=example.com
STRIPE_SECRET_KEY=sk_live_abc123
```

The script will set:
- `PROD_DOMAIN` = `example.com`
- `PROD_STRIPE_SECRET_KEY` = `sk_live_abc123`

### Notes

- Secrets are set for the current repository (detected automatically)
- Existing secrets with the same name will be overwritten
- Use `--dry-run` first to preview what will be set

