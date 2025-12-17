# Environment Files and GitHub Secrets

## Current Setup

✅ **GitHub Actions passes secrets directly to Docker Compose via environment variables.**

You do **NOT** need local `.env.dev` or `.env.prod` files for deployment. The workflow:

1. Reads secrets from GitHub (with `PROD_` or `DEV_` prefix)
2. Passes them as environment variables to the deployment script
3. Creates a temporary `.env` file on the server (in memory, not committed)
4. Docker Compose uses them to start containers

**Benefits:**
- ✅ Secrets never stored in files in the repository
- ✅ Secrets only exist temporarily on the server during deployment
- ✅ Direct connection from GitHub Secrets → Docker Compose

## Local .env Files

### For Deployment: ❌ Not Required

Local `.env` files are **not needed** for deployment since:
- GitHub Actions generates them from secrets
- They're already in `.gitignore` (won't be committed)
- The workflow handles everything automatically

### For Local Development: ✅ Optional

You may still want local `.env` files for:
- Running the app locally with `docker-compose`
- Testing changes before deployment
- Development workflows

If you keep them locally, they're safe because:
- They're in `.gitignore` (won't be committed)
- They won't interfere with deployment

## Deleting Local .env Files

**You can safely delete `.env.dev` and `.env.prod` files** if:
- ✅ All secrets are in GitHub Secrets
- ✅ You're not running the app locally
- ✅ You only deploy via GitHub Actions

To delete:
```bash
rm .env.dev .env.prod
```

## Workflow

```
Local .env files (optional)
    ↓
GitHub Secrets (required) ← You are here
    ↓
GitHub Actions generates .env files
    ↓
Copied to server
    ↓
Docker Compose uses them
```

## Verifying Secrets

To verify your secrets are set correctly:

```bash
# List all secrets (requires GitHub CLI)
gh secret list

# Or check in GitHub UI:
# Settings > Secrets and variables > Actions
```

## Updating Secrets

To update a secret:

```bash
# Using GitHub CLI
gh secret set PROD_DOMAIN --body "new-domain.com"

# Or use the sync script if you have local .env files
./scripts/sync-env-to-github-secrets.sh
```

## Summary

- ✅ **Deployment**: Uses GitHub Secrets → No local .env files needed
- ✅ **Local .env files**: Optional, safe to delete if not needed locally
- ✅ **Security**: Secrets stored securely in GitHub, never in code

