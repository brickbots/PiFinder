#! /usr/bin/bash
set -e

PIFINDER_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

cd "${PIFINDER_REPO_DIR}"
git checkout release
git pull
source "${PIFINDER_REPO_DIR}/pifinder_post_update.sh"

echo "PiFinder software update complete, please restart the Pi"
