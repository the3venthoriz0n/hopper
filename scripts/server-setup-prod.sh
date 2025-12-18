#!/bin/bash
# DigitalOcean User Data Script
# This script runs automatically when the droplet is first created
# It sets up Docker, nginx, firewall, and prepares the server for deployment

set -e

# Set non-interactive mode for all commands
export DEBIAN_FRONTEND=noninteractive

# Log everything to a file for debugging
exec > >(tee /var/log/hopper-setup.log) 2>&1

echo "🚀 Setting up DigitalOcean production server..."
echo "Started at: $(date)"

# Update system (skip upgrade to speed up initial setup - can be done later)
echo "📦 Updating system packages..."
apt-get update -y
# Skip upgrade during initial setup - can run manually later if needed
# apt-get upgrade -y

# Install Docker
if ! command -v docker &> /dev/null; then
    echo "🐳 Installing Docker..."
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
else
    echo "✅ Docker already installed"
fi

# Install Docker Compose (standalone)
if ! command -v docker compose &> /dev/null; then
    echo "📋 Installing Docker Compose..."
    apt-get install -y docker-compose-plugin
else
    echo "✅ Docker Compose already installed"
fi

# Install nginx
if ! command -v nginx &> /dev/null; then
    echo "🌐 Installing nginx..."
    apt-get install -y nginx
    systemctl enable nginx
else
    echo "✅ nginx already installed"
fi

# Configure firewall
echo "🔥 Configuring firewall..."
if command -v ufw &> /dev/null; then
    # Use --force to avoid prompts
    ufw --force enable || true
    ufw --force allow 22/tcp    # SSH
    ufw --force allow 80/tcp    # HTTP
    ufw --force allow 443/tcp   # HTTPS
    echo "✅ Firewall configured"
else
    echo "⚠️  UFW not found, skipping firewall setup"
fi

# Create app directory
APP_DIR="/opt/hopper"
echo "📁 Creating app directory at $APP_DIR..."
mkdir -p $APP_DIR
mkdir -p $APP_DIR/nginx

# Login to GHCR (optional - GitHub Actions handles this automatically)
echo "🔐 GHCR authentication:"
echo "   GitHub Actions will handle authentication automatically."
echo "   For manual pulls, you can set GHCR_TOKEN and run:"
echo "   echo \$GHCR_TOKEN | docker login ghcr.io -u USERNAME --password-stdin"

# Create docker network if it doesn't exist
echo "🌐 Creating Docker network..."
docker network create hopper_default 2>/dev/null || echo "✅ Network already exists"

echo ""
echo "✅ Production server setup complete!"
echo "Completed at: $(date)"
echo ""
echo "Setup log saved to: /var/log/hopper-setup.log"
echo ""
echo "Next steps:"
echo "1. Add your public SSH key to ~/.ssh/authorized_keys (if not already done)"
echo "2. Ensure GitHub Secrets are configured (PROD_HOST, PROD_USER, PROD_SSH_KEY, etc.)"
echo "3. Push to 'main' branch to trigger automatic deployment"
echo ""
echo "The GitHub Actions workflow will automatically:"
echo "  - Build and push Docker images to GHCR"
echo "  - Copy docker-compose.prod.yml and nginx config to $APP_DIR"
echo "  - Pass all secrets as environment variables"
echo "  - Deploy and start all services"
echo ""
echo "To manually deploy (if needed):"
echo "  cd $APP_DIR && docker compose -f docker-compose.prod.yml up -d"

