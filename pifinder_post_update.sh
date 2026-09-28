git submodule update --init --recursive

# python/tetra3 must be a symlink to the tetra3 package inside the
# cedar-solve submodule. It is deliberately untracked (see ADR 0035):
# older installs have a plain folder or an absolute symlink here, and a
# tracked version makes `git pull` refuse to update those units. Anything
# else at this path is moved aside (kept, not deleted) and the symlink is
# (re)created on every update.
TETRA3_LINK="/home/pifinder/PiFinder/python/tetra3"
TETRA3_TARGET="PiFinder/tetra3/tetra3"
if [ -e "$TETRA3_LINK" ] || [ -L "$TETRA3_LINK" ]
then
    if [ "$(readlink "$TETRA3_LINK")" != "$TETRA3_TARGET" ]
    then
        mv "$TETRA3_LINK" "/home/pifinder/tetra3_old_$(date +%Y%m%d-%H%M%S)"
    fi
fi
if ! [ -L "$TETRA3_LINK" ]
then
    ln -s "$TETRA3_TARGET" "$TETRA3_LINK"
fi

sudo pip install -r /home/pifinder/PiFinder/python/requirements.txt

# Set up migrations folder if it does not exist
if ! [ -d "/home/pifinder/PiFinder_data/migrations" ]
then
    mkdir /home/pifinder/PiFinder_data/migrations
fi

# v1.x.x
# everying prior to selecitve migrations
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v1.x.x" ]
then
    source /home/pifinder/PiFinder/migration_source/v1.x.x.sh
    touch /home/pifinder/PiFinder_data/migrations/v1.x.x
fi

# v2.1.0
# Switch to Cedar
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v2.1.0" ]
then
    source /home/pifinder/PiFinder/migration_source/v2.1.0.sh
    touch /home/pifinder/PiFinder_data/migrations/v2.1.0
fi

# v2.2.1
# Install libinput
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v2.2.1" ]
then
    source /home/pifinder/PiFinder/migration_source/v2.2.1.sh
    touch /home/pifinder/PiFinder_data/migrations/v2.2.1
fi

# v2.2.2
# Enable host usb on usb-c port
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v2.2.2" ]
then
    source /home/pifinder/PiFinder/migration_source/v2.2.2.sh
    touch /home/pifinder/PiFinder_data/migrations/v2.2.2
fi

# v2.4.0
# Switch detect to system process
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v2.4.0" ]
then
    source /home/pifinder/PiFinder/migration_source/v2.4.0.sh
    touch /home/pifinder/PiFinder_data/migrations/v2.4.0
fi

# v2.6.0
# Clear stale flop_image=true on the default Dobsonian (flip/flop now live)
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v2.6.0" ]
then
    source /home/pifinder/PiFinder/migration_source/v2.6.0.sh
    touch /home/pifinder/PiFinder_data/migrations/v2.6.0
fi

# v2.6.1
# RemoveIPC=no so SSH logouts can't reap the solver's shared memory
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v2.6.1" ]
then
    source /home/pifinder/PiFinder/migration_source/v2.6.1.sh
    touch /home/pifinder/PiFinder_data/migrations/v2.6.1
fi

# DONE
echo "Post Update Complete"

