# swap tetra3 submodule
git submodule sync
git submodule update --init --recursive

# The python/tetra3 symlink is created by pifinder_post_update.sh on every
# update. The `ln -s` that used to live here made an absolute symlink (or,
# with a leftover folder in the way, a stray link inside it), which later
# blocked `git pull` — see ADR 0035.

