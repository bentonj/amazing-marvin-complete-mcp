#!/usr/bin/env bash
# Scan the working tree AND the full git history for token-like values
# before pushing. Marvin tokens are short hex/base64-like strings; we look
# for generic high-entropy assignments plus known prefixes.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

patterns=(
    # long hex/base64 assigned to token/secret/password-like names
    '(token|secret|password|passwd|apikey|api_key)["'"'"']?\s*[:=]\s*["'"'"'][A-Za-z0-9+/_-]{16,}'
    # bearer headers with real-looking values
    'Bearer [A-Za-z0-9+/_-]{16,}'
    # private key blocks
    'BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY'
)

fail=0
for p in "${patterns[@]}"; do
    # Working tree (tracked files), excluding this script and the example env
    if git grep -InE "$p" -- ':!scripts/check-no-secrets.sh' ':!.env.example' 2>/dev/null; then
        fail=1
    fi
    # Full history
    if git log --all -p | grep -InE "$p" | grep -v 'check-no-secrets' | head -5 | grep -q .; then
        echo "MATCH IN HISTORY for pattern: $p"
        fail=1
    fi
done

if [ "$fail" -ne 0 ]; then
    echo "STOP: potential secrets found - do not push."
    exit 1
fi
echo "OK: no token-like patterns in the working tree or history."
