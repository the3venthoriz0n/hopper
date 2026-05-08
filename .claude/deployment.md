# Deployment Guide

## Overview

Both dev and prod use the same pipeline: GitHub Actions builds images, pushes to GHCR, SSHs to the target server, and runs `deploy.sh`. The only differences are the trigger and which GitHub Environment's secrets are used.

| | Dev | Prod |
|--|-----|------|
| **Trigger** | Push to `main` | Create a GitHub Release |
| **Server** | Unraid (local) | DigitalOcean |
| **URL** | hopper-dev.dunkbox.net | hopper.dunkbox.net |
| **Image tag** | `dev-{sha}` + `dev-latest` | `vX.Y.Z` + `prod-latest` |
| **Tests** | Skipped (fast deploy) | Full suite (unit + integration) |
| **SSL** | N/A (Cloudflare tunnel) | Certs deployed from secrets |
| **App directory** | `/opt/hopper-dev` | `/opt/hopper-prod` |

## How to Deploy

### Dev (automatic)

```bash
git push origin main
```

That's it. GitHub Actions will:
1. Build all images (backend, frontend, monitoring)
2. Push to GHCR with `:dev-latest` tag
3. SSH to Unraid
4. Copy compose file, nginx conf, env file, deploy script
5. Run `deploy.sh dev` (pulls images, restarts containers, health checks)

Monitor at: https://github.com/the3venthoriz0n/hopper/actions

### Dev (manual trigger)

Go to Actions → "Build and Deploy" → Run workflow → Select "dev" → Run.

Useful when you want to redeploy without a code change (e.g., secrets changed).

### Prod

1. Create a release on GitHub (tag format: `vX.Y.Z`)
2. GitHub Actions runs full test suite, then builds and deploys

```bash
git tag v5.1.0
git push origin v5.1.0
# Then create a Release on GitHub pointing to this tag
```

## GitHub Environments Setup

The workflow uses [GitHub Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments) to scope secrets per environment. No more `DEV_` / `PROD_` prefixes.

### Create environments

Go to: Repository → Settings → Environments

Create two environments: `dev` and `prod`

### Secrets to add (per environment)

Each environment needs these secrets. The secret *names* are the same in both; only the *values* differ.

#### Server / SSH

| Secret | Description | Example (dev) | Example (prod) |
|--------|-------------|---------------|----------------|
| `SSH_HOST` | Server hostname/IP | `192.168.1.x` or Tailscale IP | `your-do-droplet-ip` |
| `SSH_USER` | SSH username | `root` | `root` |
| `SSH_KEY` | Private SSH key (full PEM) | Unraid key | DO key |
| `APP_DIR` | App directory on server | `/opt/hopper-dev` | `/opt/hopper-prod` |

#### Domain / URLs

| Secret | Description | Example (dev) | Example (prod) |
|--------|-------------|---------------|----------------|
| `DOMAIN` | Base domain | `hopper-dev.dunkbox.net` | `hopper.dunkbox.net` |
| `FRONTEND_URL` | Full frontend URL | `https://hopper-dev.dunkbox.net` | `https://hopper.dunkbox.net` |
| `BACKEND_URL` | Full backend URL | `https://hopper-dev.dunkbox.net` | `https://hopper.dunkbox.net` |

#### Cloudflare

| Secret | Description |
|--------|-------------|
| `CLOUDFLARE_ACCESS_AUD_TAG` | Cloudflare Access audience tag |
| `CLOUDFLARE_ACCESS_TEAM_DOMAIN` | Cloudflare Access team domain |

#### OAuth (Platform Integrations)

| Secret | Description |
|--------|-------------|
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `GOOGLE_PROJECT_ID` | Google Cloud project ID |
| `TIKTOK_CLIENT_KEY` | TikTok app client key |
| `TIKTOK_CLIENT_SECRET` | TikTok app client secret |
| `INSTAGRAM_APP_ID` | Instagram/Facebook app ID |
| `INSTAGRAM_APP_SECRET` | Instagram/Facebook app secret |

#### Database / Security

| Secret | Description |
|--------|-------------|
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `ENCRYPTION_KEY` | Fernet encryption key (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |

#### Stripe

| Secret | Description |
|--------|-------------|
| `STRIPE_SECRET_KEY` | Stripe secret key (`sk_test_...` or `sk_live_...`) |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `STRIPE_PRICING_TABLE_ID` | Stripe pricing table ID |
| `STRIPE_API_VERSION` | Stripe API version (e.g., `2024-11-20.acacia`) |

#### Email

| Secret | Description |
|--------|-------------|
| `RESEND_API_KEY` | Resend API key |
| `RESEND_FROM_EMAIL` | From email address |

#### Monitoring

| Secret | Description |
|--------|-------------|
| `GRAFANA_PASSWORD` | Grafana admin password |
| `LOG_LEVEL` | Log level (`DEBUG` for dev, `INFO` for prod) |

#### Storage (Cloudflare R2)

| Secret | Description |
|--------|-------------|
| `R2_ACCOUNT_ID` | Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | R2 access key ID |
| `R2_SECRET_ACCESS_KEY` | R2 secret access key |
| `R2_BUCKET_NAME` | R2 bucket name |
| `R2_ENDPOINT_URL` | R2 endpoint URL |
| `R2_PUBLIC_DOMAIN` | R2 public domain (optional) |
| `R2_VALIDATE_CUSTOM_DOMAIN_URLS` | Validate custom domain URLs (`true`/`false`) |
| `R2_URL_VALIDATION_TIMEOUT` | URL validation timeout in seconds |

#### SSL (prod only)

| Secret | Description |
|--------|-------------|
| `SSL_CERT` | SSL certificate PEM |
| `SSL_KEY` | SSL private key PEM |

## One-Time Server Setup

### Unraid (dev)

```bash
# Create app directory
mkdir -p /opt/hopper-dev/nginx /opt/hopper-dev/scripts

# Create Docker network (if it doesn't exist)
docker network create hopper_default

# Auth to GHCR (use a GitHub PAT with read:packages scope)
docker login ghcr.io -u the3venthoriz0n
```

### DigitalOcean (prod)

Same as above but at `/opt/hopper-prod`. Already set up.

## Rollback

### Dev
Re-run a previous successful workflow from the Actions tab, or:
```bash
# Manual: trigger workflow_dispatch with "dev" environment
```

### Prod
Re-run the workflow for the previous release tag, or create a new release pointing to the older commit.

## Local Development

For fast frontend iteration without waiting for CI:

```bash
cd frontend
REACT_APP_BACKEND_URL=https://hopper-dev.dunkbox.net REACT_APP_ENVIRONMENT=development npm start
```

This runs React dev server on localhost with hot reload, talking to the dev backend on Unraid.

## Architecture

```
git push main ──→ GitHub Actions ──→ GHCR ──→ Unraid (dev)
git release    ──→ GitHub Actions ──→ GHCR ──→ DigitalOcean (prod)

No code on servers. Only:
  - docker-compose.{env}.yml (scp'd by CI)
  - .env.{env} (assembled from GitHub secrets by CI)
  - nginx/{env}-hopper.conf (scp'd by CI)
  - deploy.sh (scp'd by CI)
  - Docker volumes (postgres, redis, grafana data)
```
