# swap tetra3 submodule
#git submodule set-url -- python/PiFinder/tetra3 https://github.com/smroid/cedar-solve
git submodule sync
git submodule update --init --recursive
#cd /home/pifinder/PiFinder/python/PiFinder/tetra3
#git checkout 38c3f48
#git pull

# Set up symlink
ln -s /home/pifinder/PiFinder/python/PiFinder/tetra3/tetra3 /home/pifinder/PiFinder/python/tetra3

