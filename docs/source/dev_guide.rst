.. _dev_guide:

Developer Guide
===============

If you are a developer, like to tinke with the code, troubleshoot deeper or contribute to the project: this guide helps you to do all these cool things. 

Getting or contributing to the sources
--------------------------------------

If you have questions, you the quickest way is to ask in the `PiFinder Discord server <https://discord.gg/Nk5fHcAtWD>`_ in the section "support-software". 

If you are serious about an error or you have seen a bug, then please feel free to open an issue here on GitHub. Please describe exacactly what you found, what you expected and how you found the issue. The more desciptive and precise you are, the better. This helps a lot to speed up things. 

Getting or contributing to the sources
--------------------------------------

If you are serious about contributing code or help with the documentation, best is to fork the code into your own GitHub account. From there you can do a pull request to the original code. If you are a programmer you should already know the procedure. If not, here is how you do this: 

* `GitHub Docs - About pull requests <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests>`_
* `GitHub Docs - Creating a pull request <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request>`_
* `Youtube - How To Pull Request in 3 Minutes <https://www.youtube.com/watch?v=jRLGobWwA3Y>`_

Setup a development environment
-------------------------------

Python: Version 3.9 or 3.10 python with a working `pip tool chain <https://pypi.org/project/pip/>`_
OS:     Debian Buster (Bookworm to come)

Install python dependencies
...........................

For running PiFinder, you need to install some python libraries in certain versions. These lists can be installed via `pip tool chain <https://pypi.org/project/pip/>`_  and are separeted in two files:

```
pip install -r requirements.txt
pip install -r requirements_dev.txt
```

Install Hipparcos catalog
...........................

The hipparcos catalog will be downloaded to another location: ```/home/pifinder/PiFinder/astro_data/```

```wget -O /home/pifinder/PiFinder/astro_data/hip_main.dat https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat```

Tetra3 solver
...........................

The `Tetra3 Solver <https://github.com/esa/tetra3>` is a "fast lost-in-space plate solver for star trackers written in Python". It is the next gen solver, that PiFinder uses.

```
cd python/PiFinder
git clone https://github.com/esa/tetra3.git
```

Running in debug mode 
---------------------

If you installed everything, you like to develop and test your code. Or you like to see error messages. 

Run the following command from the ```./python``` folder to start PiFinder in the debugging mode. You can enable debug information by passing the '-x' flag:
```
cd /home/pifinder/PiFinder/python
python3 -m PiFinder.main -fh -k server --camera debug -x
```

Troubleshooting
---------------

My app crashes
..............

When crashing, there are many unrelated stack traces running. Search for the relevant one. The rest is not important, these are the other threads stopping.

My IMU seems not to be working
------------------------------

First power up the unit and look at the Status page while moving it around.

- .. image:: images/user_guide/STATUS_001_docs.png

