# swap tetra3 submodule
git submodule sync
git submodule update --init --recursive

# Set up symlink
ln -s /home/pifinder/PiFinder/python/PiFinder/tetra3/tetra3 /home/pifinder/PiFinder/python/tetra3

