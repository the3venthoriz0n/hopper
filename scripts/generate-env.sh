#!/bin/bash
# Generate .env file from GitHub Secrets
# Usage: ./generate-env.sh [dev|prod]

set -e

ENV=${1:-prod}
ENV_FILE=".env.${ENV}"

if [ "$ENV" != "dev" ] && [ "$ENV" != "prod" ]; then
    echo "❌ Invalid environment: $ENV. Use 'dev' or 'prod'"
    exit 1
fi

echo "📝 Generating $ENV_FILE from GitHub Secrets..."

# Prefix for secrets (PROD_ or DEV_)
PREFIX=$(echo "$ENV" | tr '[:lower:]' '[:upper:]')

cat > "$ENV_FILE" << EOF
# Generated .env file for $ENV environment
# Do not edit manually - generated from GitHub Secrets

# Environment
ENVIRONMENT=$([ "$ENV" == "prod" ] && echo "production" || echo "development")
LOG_LEVEL=\${${PREFIX}_LOG_LEVEL:-$([ "$ENV" == "prod" ] && echo "INFO" || echo "DEBUG")}

# Domain Configuration
DOMAIN=\${${PREFIX}_DOMAIN}
FRONTEND_URL=\${${PREFIX}_FRONTEND_URL}
BACKEND_URL=\${${PREFIX}_BACKEND_URL}

# Cloudflare Access
CLOUDFLARE_ACCESS_AUD_TAG=\${${PREFIX}_CLOUDFLARE_ACCESS_AUD_TAG}
CLOUDFLARE_ACCESS_TEAM_DOMAIN=\${${PREFIX}_CLOUDFLARE_ACCESS_TEAM_DOMAIN}

# Google OAuth (YouTube)
GOOGLE_CLIENT_ID=\${${PREFIX}_GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=\${${PREFIX}_GOOGLE_CLIENT_SECRET}
GOOGLE_PROJECT_ID=\${${PREFIX}_GOOGLE_PROJECT_ID}

# TikTok OAuth
TIKTOK_CLIENT_KEY=\${${PREFIX}_TIKTOK_CLIENT_KEY}
TIKTOK_CLIENT_SECRET=\${${PREFIX}_TIKTOK_CLIENT_SECRET}

# Instagram/Facebook OAuth
FACEBOOK_APP_ID=\${${PREFIX}_FACEBOOK_APP_ID}
FACEBOOK_APP_SECRET=\${${PREFIX}_FACEBOOK_APP_SECRET}

# Database
POSTGRES_PASSWORD=\${${PREFIX}_POSTGRES_PASSWORD}

# Security
ENCRYPTION_KEY=\${${PREFIX}_ENCRYPTION_KEY}

# Stripe Configuration
STRIPE_SECRET_KEY=\${${PREFIX}_STRIPE_SECRET_KEY}
STRIPE_PUBLISHABLE_KEY=\${${PREFIX}_STRIPE_PUBLISHABLE_KEY}
STRIPE_WEBHOOK_SECRET=\${${PREFIX}_STRIPE_WEBHOOK_SECRET}
STRIPE_PRICING_TABLE_ID=\${${PREFIX}_STRIPE_PRICING_TABLE_ID}
STRIPE_API_VERSION=\${${PREFIX}_STRIPE_API_VERSION:-2024-11-20.acacia}

# Email (Resend)
RESEND_API_KEY=\${${PREFIX}_RESEND_API_KEY}
RESEND_FROM_EMAIL=\${${PREFIX}_RESEND_FROM_EMAIL}

# Monitoring
GRAFANA_PASSWORD=\${${PREFIX}_GRAFANA_PASSWORD:-admin}
EOF

echo "✅ Generated $ENV_FILE"
echo "⚠️  Note: This file uses variable substitution. Ensure secrets are set in GitHub."

