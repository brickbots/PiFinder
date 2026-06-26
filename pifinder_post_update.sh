PIFINDER_REPO_DIR="${PIFINDER_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

git submodule update --init --recursive
sudo python3 -m pip install --break-system-packages -r "${PIFINDER_REPO_DIR}/python/requirements.txt"

# Set up migrations folder if it does not exist
if ! [ -d "${PIFINDER_DATA_DIR}/migrations" ]
then
    mkdir -p "${PIFINDER_DATA_DIR}/migrations"
fi

# v1.x.x
# everying prior to selecitve migrations
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v1.x.x" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v1.x.x.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v1.x.x"
fi

# v2.1.0
# Switch to Cedar
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.1.0" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.1.0.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.1.0"
fi

# v2.2.1
# Install libinput
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.2.1" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.2.1.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.2.1"
fi

# v2.2.2
# Enable host usb on usb-c port
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.2.2" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.2.2.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.2.2"
fi

# v2.4.0
# Switch detect to system process
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.4.0" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.4.0.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.4.0"
fi

# v2.6.0
# Clear stale flop_image=true on the default Dobsonian (flip/flop now live)
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.6.0" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.6.0.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.6.0"
fi

# DONE
echo "Post Update Complete"
