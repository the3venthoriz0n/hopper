#!/bin/bash
# Setup automatic SSL certificate renewal
# This script should be run on the production server

set -e

echo "🔄 Setting up SSL certificate auto-renewal..."

# Create renewal script
cat > /usr/local/bin/renew-ssl-certs.sh << 'EOF'
#!/bin/bash
# Renew SSL certificates and copy to Docker volumes

set -e

DOMAINS=(
    "hopper.dunkbox.net"
    "api.dunkbox.net"
    "grafana.hopper.dunkbox.net"
)

# Renew certificates
certbot renew --quiet --webroot --webroot-path=/var/lib/docker/volumes/hopper_certbot_www/_data

# Copy renewed certificates to Docker volumes
for domain in "${DOMAINS[@]}"; do
    if [ -f "/etc/letsencrypt/live/$domain/fullchain.pem" ]; then
        cp "/etc/letsencrypt/live/$domain/fullchain.pem" "/var/lib/docker/volumes/hopper_ssl_certs/_data/$domain/"
        cp "/etc/letsencrypt/live/$domain/privkey.pem" "/var/lib/docker/volumes/hopper_ssl_certs/_data/$domain/"
    fi
done

# Reload nginx to pick up new certificates
docker exec prod-hopper-nginx nginx -s reload

echo "$(date): SSL certificates renewed" >> /var/log/ssl-renewal.log
EOF

chmod +x /usr/local/bin/renew-ssl-certs.sh

# Add to crontab (run twice daily at 3am and 3pm)
(crontab -l 2>/dev/null | grep -v renew-ssl-certs.sh; echo "0 3,15 * * * /usr/local/bin/renew-ssl-certs.sh") | crontab -

echo "✅ Auto-renewal setup complete!"
echo "Certificates will be renewed twice daily at 3am and 3pm"
echo ""

