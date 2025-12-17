#!/bin/bash
set -e

echo "🚀 Setting up home development server..."

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo "⚠️  This script should be run with sudo for system packages"
    echo "   Some steps may require manual intervention"
fi

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "❌ Cannot detect OS"
    exit 1
fi

# Install Docker (Ubuntu/Debian)
if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
    if ! command -v docker &> /dev/null; then
        echo "🐳 Installing Docker..."
        apt-get update
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
else
    echo "⚠️  OS $OS detected. Please install Docker manually:"
    echo "   https://docs.docker.com/get-docker/"
fi

# Install Docker Compose
if ! command -v docker compose &> /dev/null; then
    echo "📋 Installing Docker Compose..."
    if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
        apt-get install -y docker-compose-plugin
    else
        echo "⚠️  Please install Docker Compose manually"
    fi
else
    echo "✅ Docker Compose already installed"
fi

# Create app directory
APP_DIR="/opt/hopper-dev"
echo "📁 Creating app directory at $APP_DIR..."
mkdir -p $APP_DIR

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
echo "✅ Development server setup complete!"
echo ""
echo "Next steps:"
echo "1. Copy docker-compose.dev.yml and .env.dev to $APP_DIR"
echo "2. Add your public SSH key to ~/.ssh/authorized_keys"
echo "3. Run: cd $APP_DIR && docker compose -f docker-compose.dev.yml up -d"

