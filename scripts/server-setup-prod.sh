#!/bin/bash
set -e

echo "🚀 Setting up DigitalOcean production server..."

# Update system
echo "📦 Updating system packages..."
apt-get update
apt-get upgrade -y

# Install Docker
if ! command -v docker &> /dev/null; then
    echo "🐳 Installing Docker..."
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update
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
    ufw --force enable
    ufw allow 22/tcp    # SSH
    ufw allow 80/tcp    # HTTP
    ufw allow 443/tcp   # HTTPS
    echo "✅ Firewall configured"
else
    echo "⚠️  UFW not found, skipping firewall setup"
fi

# Create app directory
APP_DIR="/opt/hopper"
echo "📁 Creating app directory at $APP_DIR..."
mkdir -p $APP_DIR
mkdir -p $APP_DIR/nginx

# Login to GHCR
echo "🔐 Setting up GHCR authentication..."
if [ -z "$GHCR_TOKEN" ]; then
    echo "⚠️  GHCR_TOKEN not set. You'll need to run:"
    echo "   echo \$GHCR_TOKEN | docker login ghcr.io -u USERNAME --password-stdin"
else
    echo "$GHCR_TOKEN" | docker login ghcr.io -u $(whoami) --password-stdin || {
        echo "⚠️  GHCR login failed. You may need to set GHCR_TOKEN and run manually."
    }
fi

# Create docker network if it doesn't exist
echo "🌐 Creating Docker network..."
docker network create hopper_default 2>/dev/null || echo "✅ Network already exists"

echo ""
echo "✅ Production server setup complete!"
echo ""
echo "Next steps:"
echo "1. Copy docker-compose.prod.yml and .env.prod to $APP_DIR"
echo "2. Copy nginx/hopper.conf to $APP_DIR/nginx/"
echo "3. Add your public SSH key to ~/.ssh/authorized_keys"
echo "4. Run: cd $APP_DIR && docker compose -f docker-compose.prod.yml up -d"

