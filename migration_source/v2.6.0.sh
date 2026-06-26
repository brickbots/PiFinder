PIFINDER_REPO_DIR="${PIFINDER_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

# Clear stale flop_image=true on the shipped "Generic Dobsonian" default.
# flip/flop are now applied to the object-detail image; a Dobsonian needs
# neither flag, so repair any persisted config that froze the bad default.
# Idempotent and version-gated by pifinder_post_update.sh. See
# docs/adr/0003-object-image-orientation.md.
python "${PIFINDER_REPO_DIR}/python/PiFinder/migrations/v2_6_0_dob_flop.py" "${PIFINDER_DATA_DIR}/config.json"
