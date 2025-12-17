#!/bin/bash
# Sync .env.dev and .env.prod files to GitHub Secrets
# Usage: ./sync-env-to-github-secrets.sh [--dry-run] [--skip-confirm]

set -e

DRY_RUN=false
SKIP_CONFIRM=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-confirm)
            SKIP_CONFIRM=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--dry-run] [--skip-confirm]"
            exit 1
            ;;
    esac
done

# Check if GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) is not installed."
    echo "   Install it from: https://cli.github.com/"
    exit 1
fi

# Check if user is authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ Not authenticated with GitHub CLI."
    echo "   Run: gh auth login"
    exit 1
fi

# Get repository name
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "")
if [ -z "$REPO" ]; then
    echo "❌ Could not determine repository. Are you in a git repository?"
    exit 1
fi

echo "📦 Repository: $REPO"
echo ""

# Function to parse .env file and set secrets
sync_env_file() {
    local env_file=$1
    local prefix=$2
    
    if [ ! -f "$env_file" ]; then
        echo "⚠️  File not found: $env_file (skipping)"
        return
    fi
    
    echo "📄 Processing $env_file with prefix: ${prefix}_"
    echo ""
    
    local count=0
    local skipped=0
    
    # Read file line by line
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip empty lines and comments
        if [[ -z "$line" ]] || [[ "$line" =~ ^[[:space:]]*# ]]; then
            continue
        fi
        
        # Skip lines that don't contain =
        if [[ ! "$line" =~ = ]]; then
            continue
        fi
        
        # Extract key and value
        key=$(echo "$line" | cut -d'=' -f1 | xargs)
        value=$(echo "$line" | cut -d'=' -f2- | xargs)
        
        # Skip if key is empty
        if [ -z "$key" ]; then
            continue
        fi
        
        # Skip if value starts with ${ (variable substitution)
        if [[ "$value" =~ ^\$\{ ]]; then
            echo "  ⏭️  Skipping $key (contains variable substitution)"
            skipped=$((skipped + 1))
            continue
        fi
        
        # Skip if value is empty
        if [ -z "$value" ]; then
            echo "  ⏭️  Skipping $key (empty value)"
            skipped=$((skipped + 1))
            continue
        fi
        
        # Construct secret name with prefix
        secret_name="${prefix}_${key}"
        
        # Remove any existing prefix if accidentally duplicated
        secret_name=$(echo "$secret_name" | sed "s/^${prefix}_${prefix}_/${prefix}_/")
        
        if [ "$DRY_RUN" = true ]; then
            echo "  🔍 Would set: $secret_name = ${value:0:20}..."
            count=$((count + 1))
        else
            echo -n "  🔐 Setting $secret_name... "
            
            # Use GitHub CLI to set secret
            if echo -n "$value" | gh secret set "$secret_name" &> /dev/null; then
                echo "✅"
                count=$((count + 1))
            else
                echo "❌ Failed"
            fi
        fi
    done < "$env_file"
    
    echo ""
    if [ "$DRY_RUN" = true ]; then
        echo "  📊 Would set $count secrets (skipped $skipped)"
    else
        echo "  📊 Set $count secrets (skipped $skipped)"
    fi
    echo ""
}

# Confirm before proceeding
if [ "$SKIP_CONFIRM" != true ] && [ "$DRY_RUN" != true ]; then
    echo "⚠️  This will set GitHub secrets for repository: $REPO"
    echo "   Secrets will be prefixed with PROD_ or DEV_"
    echo ""
    read -p "Continue? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
    echo ""
fi

# Process .env.prod
if [ -f ".env.prod" ]; then
    sync_env_file ".env.prod" "PROD"
else
    echo "⚠️  .env.prod not found (skipping)"
    echo ""
fi

# Process .env.dev
if [ -f ".env.dev" ]; then
    sync_env_file ".env.dev" "DEV"
else
    echo "⚠️  .env.dev not found (skipping)"
    echo ""
fi

# Summary
echo "✅ Done!"
if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "This was a dry run. No secrets were actually set."
    echo "Run without --dry-run to set the secrets."
fi

