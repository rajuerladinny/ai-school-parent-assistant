#!/usr/bin/env bash
# Deploy the committed code to a Hugging Face Docker Space.
#
# Usage (from the repository root, in Git Bash):
#   scripts/deploy_hf_space.sh <hf-username>/<space-name>
#
# The Space must already exist (SDK: Docker). Git asks for your Hugging Face username
# and an access token with write permission the first time; it is stored by your
# git credential manager, never by this script. Only committed files are deployed.
set -euo pipefail

SPACE="${1:?Usage: scripts/deploy_hf_space.sh <hf-username>/<space-name>}"
ROOT="$(git rev-parse --show-toplevel)"
REV="$(git -C "$ROOT" rev-parse --short HEAD)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git -C "$ROOT" archive HEAD | tar -x -C "$TMP"

# Hugging Face reads the Space's settings from README.md front matter, and rejects
# plain binary files, so swap in the Space README and drop files the demo doesn't need.
cp "$ROOT/deploy/huggingface/README.md" "$TMP/README.md"
rm -rf "$TMP/docs/images" "$TMP/.github" "$TMP/deploy"

cd "$TMP"
git init -q -b main
git add -A
git -c user.name="deploy" -c user.email="deploy@localhost" commit -q -m "Deploy ai-school-parent-assistant @ $REV"
git push --force "https://huggingface.co/spaces/$SPACE" main
echo "Deployed $REV to https://huggingface.co/spaces/$SPACE"
