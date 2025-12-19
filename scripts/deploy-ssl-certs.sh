#!/bin/bash
# Deploy SSL certificates from environment variables to Docker volumes
# This script is called during deployment to set up Cloudflare Origin Certificates
# Uses a single certificate/key pair for all domains (wildcard certificate)

set -e

ENV=${1:-prod}
CERT_DIR="/var/lib/docker/volumes/hopper_ssl_certs/_data"

echo "🔒 Deploying SSL certificates for $ENV environment..."

# Only deploy for production
if [ "$ENV" != "prod" ]; then
    echo "⏭️  Skipping SSL certificate deployment for $ENV environment"
    exit 0
fi

# Check if certificate and key are set
if [ -z "$PROD_SSL_CERT" ] || [ -z "$PROD_SSL_KEY" ]; then
    echo "⚠️  Warning: SSL certificate or key not set (PROD_SSL_CERT, PROD_SSL_KEY)"
    echo "   Skipping SSL certificate deployment"
    exit 0
fi

# Create certificate directory
mkdir -p "$CERT_DIR"

# Domains that need the certificate
DOMAINS=(
    "hopper.dunkbox.net"
    "api.dunkbox.net"
    "grafana.hopper.dunkbox.net"
)

# Deploy the same certificate to all domains
for domain in "${DOMAINS[@]}"; do
    domain_dir="$CERT_DIR/$domain"
    mkdir -p "$domain_dir"
    
    # Write certificate (as fullchain.pem for nginx)
    echo "$PROD_SSL_CERT" > "$domain_dir/fullchain.pem"
    chmod 644 "$domain_dir/fullchain.pem"
    
    # Write private key
    echo "$PROD_SSL_KEY" > "$domain_dir/privkey.pem"
    chmod 600 "$domain_dir/privkey.pem"
    
    echo "✅ Deployed SSL certificate for $domain"
done

echo "✅ SSL certificate deployment complete!"
echo "   Certificates are in: $CERT_DIR"

