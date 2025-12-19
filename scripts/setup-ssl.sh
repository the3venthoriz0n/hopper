#!/bin/bash
# Setup SSL certificates for production using certbot
# This script should be run on the production server

set -e

DOMAINS=(
    "hopper.dunkbox.net"
    "api.dunkbox.net"
    "hopper-grafana-prod.dunkbox.net"
)

EMAIL="${CERTBOT_EMAIL:-your-email@example.com}"  # Set CERTBOT_EMAIL env var or edit here

echo "🔒 Setting up SSL certificates for production domains..."
echo "Email: $EMAIL"
echo ""

# Check if certbot is installed
if ! command -v certbot &> /dev/null; then
    echo "❌ certbot is not installed. Installing..."
    apt-get update
    apt-get install -y certbot
fi

# Create directories for certificates
mkdir -p /var/lib/docker/volumes/hopper_ssl_certs/_data
mkdir -p /var/lib/docker/volumes/hopper_certbot_www/_data

# Get certificates for each domain
for domain in "${DOMAINS[@]}"; do
    echo "📜 Obtaining certificate for $domain..."
    
    # Create domain-specific directory
    mkdir -p "/var/lib/docker/volumes/hopper_ssl_certs/_data/$domain"
    
    # Request certificate using webroot method
    certbot certonly \
        --webroot \
        --webroot-path=/var/lib/docker/volumes/hopper_certbot_www/_data \
        --email "$EMAIL" \
        --agree-tos \
        --no-eff-email \
        --keep-until-expiring \
        -d "$domain"
    
    # Copy certificates to Docker volume location
    if [ -f "/etc/letsencrypt/live/$domain/fullchain.pem" ]; then
        cp "/etc/letsencrypt/live/$domain/fullchain.pem" "/var/lib/docker/volumes/hopper_ssl_certs/_data/$domain/"
        cp "/etc/letsencrypt/live/$domain/privkey.pem" "/var/lib/docker/volumes/hopper_ssl_certs/_data/$domain/"
        echo "✅ Certificate for $domain installed successfully"
    else
        echo "❌ Failed to obtain certificate for $domain"
        exit 1
    fi
done

echo ""
echo "✅ All certificates obtained successfully!"
echo ""
echo "📋 Next steps:"
echo "1. Restart nginx container: docker restart prod-hopper-nginx"
echo "2. Set Cloudflare SSL/TLS mode to 'Full (strict)'"
echo "3. Set up auto-renewal (see setup-ssl-renewal.sh)"
echo ""

