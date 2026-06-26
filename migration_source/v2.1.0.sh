PIFINDER_REPO_DIR="${PIFINDER_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

# swap tetra3 submodule
git submodule sync
git submodule update --init --recursive

# Set up symlink
ln -sfn "${PIFINDER_REPO_DIR}/python/PiFinder/tetra3/tetra3" "${PIFINDER_REPO_DIR}/python/tetra3"
