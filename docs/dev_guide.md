# PiFinder software development guide

Nothing here yet... if you have questions about the software or would like to contribute feel free to open an issue or a pull request!

# getting the source

If you are serious about contributing, best is to fork the code on github
into your own project

# environment

PiFinder needs 3.9 or 3.10 python with a working pip

# setup

## install python dependencies
pip install -r requirements.txt
pip install -r requirements_dev.txt

## install other dependencies

### Hipparcos catalog

Download the hipparcos catalog, change the download location.

'''wget -O /home/pifinder/PiFinder/astro_data/hip_main.dat https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat'''

### Tetra3 solver

'''
cd python/PiFinder
git clone https://github.com/esa/tetra3.git
'''

# running

Run the following command from the ./python folder
'''python3 -m PiFinder.main -fh -k server --camera debug -x'''


# debugging

You can enable debug information by passing the '-x' flag

When crashing, there are many unrelated stack traces, search for the relevant
one, the rest are the other threads stopping.

