#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
exec > >(tee /var/log/hopper-setup.log) 2>&1

echo "🚀 Setting up DigitalOcean production server..."

# Update system
echo "📦 Updating system packages..."
apt-get update -y

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
fi

# Install nginx
if ! command -v nginx &> /dev/null; then
    echo "🌐 Installing nginx..."
    apt-get install -y nginx
    systemctl enable nginx
fi

# Configure firewall - CRITICAL ORDER
echo "🔥 Configuring firewall..."
if command -v ufw &> /dev/null; then
    # IMPORTANT: Set rules BEFORE enabling
    ufw --force reset  # Start fresh
    ufw default deny incoming
    ufw default allow outgoing
    
    # Add rules BEFORE enabling
    ufw allow 22/tcp    # SSH - MUST be first!
    ufw allow 80/tcp    # HTTP
    ufw allow 443/tcp   # HTTPS
    
    # Enable firewall AFTER rules are set
    ufw --force enable
    
    # Verify it worked
    echo "Firewall status:"
    ufw status numbered
    
    if ufw status | grep -q "22/tcp"; then
        echo "✅ Firewall configured - SSH access preserved"
    else
        echo "❌ WARNING: SSH rule not found! You may be locked out!"
        ufw --force disable  # Disable to prevent lockout
    fi
fi

# Create app directory
APP_DIR="/opt/hopper-prod"
echo "📁 Creating app directory..."
mkdir -p $APP_DIR/nginx

# Create docker network
echo "🌐 Creating Docker network..."
docker network create hopper_default 2>/dev/null || true

echo "✅ Setup complete at $(date)"