#!/usr/bin/env bash
set -e

echo "[BOOTSTRAP] Setting up SSH for GitHub..."

# Create SSH directory
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Decode SSH private key from the Replit secret
if [ -n "$SSH_PRIVATE_KEY_B64" ]; then
  echo "$SSH_PRIVATE_KEY_B64" | base64 -d > ~/.ssh/id_ed25519
  chmod 600 ~/.ssh/id_ed25519
else
  echo "[ERROR] SSH_PRIVATE_KEY_B64 not set!"
  exit 1
fi

# Add GitHub to known_hosts (avoids "Host key verification failed")
ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null || true
chmod 644 ~/.ssh/known_hosts

# Start ssh-agent and load the key
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

echo "[BOOTSTRAP] SSH setup complete."
