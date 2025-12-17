# Deployment Setup Guide

## Prerequisites

1. **GitHub Repository**: Ensure your code is in a GitHub repository
2. **DigitalOcean Droplet**: Create a droplet (Ubuntu 22.04 LTS, 4GB RAM minimum recommended)
3. **Home Server**: Ensure your home server has Docker and Docker Compose installed

## SSH Keys

SSH keys have been generated in `deployment-keys/`:
- `deployment-keys/dev_rsa.pub` - Public key for dev server
- `deployment-keys/prod_rsa.pub` - Public key for prod server
- `deployment-keys/dev_rsa` - Private key (add to GitHub Secrets as `DEV_SSH_KEY`)
- `deployment-keys/prod_rsa` - Private key (add to GitHub Secrets as `PROD_SSH_KEY`)

## GitHub Secrets Setup

**See [GITHUB_SECRETS.md](GITHUB_SECRETS.md) for the complete list of required secrets.**

All secrets should be prefixed with `PROD_` for production or `DEV_` for development.

### Quick Start - Minimum Required Secrets:

**Production:**
- `PROD_HOST` - DigitalOcean droplet IP or hostname
- `PROD_USER` - SSH user (typically `root`)
- `PROD_SSH_KEY` - Contents of `deployment-keys/prod_rsa`
- `PROD_DOMAIN`, `PROD_FRONTEND_URL`, `PROD_BACKEND_URL`
- `PROD_POSTGRES_PASSWORD`, `PROD_ENCRYPTION_KEY`
- OAuth secrets (Google, TikTok, Facebook)
- Stripe secrets
- Email/Resend secrets

**Development:**
- `DEV_HOST` - Home server IP or hostname
- `DEV_USER` - SSH user for home server
- `DEV_SSH_KEY` - Contents of `deployment-keys/dev_rsa`
- `DEV_DOMAIN`, `DEV_FRONTEND_URL`, `DEV_BACKEND_URL`
- `DEV_POSTGRES_PASSWORD`, `DEV_ENCRYPTION_KEY`
- OAuth secrets (Google, TikTok, Facebook)
- Stripe secrets
- Email/Resend secrets

**Note:** `GITHUB_TOKEN` is automatically provided by GitHub Actions for GHCR authentication.

**Branch Triggering:**
- `main` branch → Production deployment
- `dev` branch → Development deployment
- `dev/**` branches (e.g., `dev/configureHosting`) → Development deployment

## Server Setup

### Production (DigitalOcean)

1. SSH into your droplet
2. Add the public key to authorized_keys:
   ```bash
   cat deployment-keys/prod_rsa.pub >> ~/.ssh/authorized_keys
   ```
3. Run the setup script:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/server-setup-prod.sh | bash
   ```
   Or manually:
   ```bash
   chmod +x scripts/server-setup-prod.sh
   sudo ./scripts/server-setup-prod.sh
   ```
4. Set GHCR_TOKEN environment variable (or login manually):
   ```bash
   echo $GHCR_TOKEN | docker login ghcr.io -u YOUR_USERNAME --password-stdin
   ```
   
   **Note:** You don't need to copy `.env.prod` files manually. GitHub Actions will generate and deploy them automatically from GitHub Secrets.

### Development (Home Server)

1. SSH into your home server
2. Add the public key to authorized_keys:
   ```bash
   cat deployment-keys/dev_rsa.pub >> ~/.ssh/authorized_keys
   ```
3. Run the setup script:
   ```bash
   chmod +x scripts/server-setup-dev.sh
   sudo ./scripts/server-setup-dev.sh
   ```
4. Set GHCR_TOKEN environment variable (or login manually):
   ```bash
   echo $GHCR_TOKEN | docker login ghcr.io -u YOUR_USERNAME --password-stdin
   ```
   
   **Note:** You don't need to copy `.env.dev` files manually. GitHub Actions will generate and deploy them automatically from GitHub Secrets.

## Cloudflare Configuration

1. Point your domain DNS A record to your DigitalOcean droplet IP
2. Set SSL/TLS mode to "Full" or "Full Strict"
3. Configure firewall rules as needed

## First Deployment

1. Push to `main` branch → triggers production deployment
2. Push to `dev` branch → triggers development deployment

The workflow will:
- Build all Docker images
- Push to GitHub Container Registry (GHCR)
- Deploy to the appropriate server
- Restart services with new images

## Manual Deployment

If you need to deploy manually:

```bash
# On the server
cd /opt/hopper  # or /opt/hopper-dev for dev
GITHUB_REPOSITORY=YOUR_USERNAME/YOUR_REPO ./deploy.sh prod abc1234  # or dev for dev
```

## Troubleshooting

### Images not found
- Ensure GHCR_TOKEN is set and you're logged in
- Check that images were pushed to GHCR in the Actions tab

### Deployment fails
- Check SSH key is correctly added to GitHub Secrets
- Verify server is accessible via SSH
- Check server logs: `docker compose -f docker-compose.prod.yml logs`

### Services not starting
- Check environment variables in `.env.prod` or `.env.dev`
- Verify Docker network exists: `docker network ls | grep hopper`
- Check service logs: `docker compose -f docker-compose.prod.yml logs SERVICE_NAME`

