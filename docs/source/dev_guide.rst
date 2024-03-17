.. _dev_guide:

Developer Guide
===============

If you are a developer, like to tinke with the code, troubleshoot deeper or contribute to the project: this guide helps you to do all these cool things. 

Submitting issues, bugs and ideas
---------------------------------

Generally the rule applies: the more desciptive and precise you are, the better. T Please always describe exacactly what you found, what you expected and how you found the issue. Work with error logs or show us pictures of the problem or maker screenshots. his helps a lot to speed up things.

Depending on the complexity, it is probably wise, to discuss your issue on the discord server in advance. There are a lot of users and developers online. 

- If you have a **question**, that is likely to be answered, the quickest way is to ask in the `PiFinder Discord server <https://discord.gg/Nk5fHcAtWD>`_ in the section "support-software". 

- If you are serious about an **error** or you have seen a **bug**, then please feel free to open an issue here on GitHub.  

- Also, if you like to **submit your ideas**, you can use the issue page. 


Fork me - getting or contributing to the sources with pull request
------------------------------------------------------------------

If you like to alter or contribute new functionalities, fix errors in the code, or even just help with the documentation, best is to **fork** the code into your own GitHub account. Also, you can tell this the developers in the above mentioned `PiFinder Discord server <https://discord.gg/Nk5fHcAtWD>`_ .

From there you can do a **pull request** to the original code. If you are a programmer you should already know the procedure. If not, here is how you do this: 

* `GitHub Docs - About pull requests <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests>`_
* `GitHub Docs - Creating a pull request <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request>`_
* `Youtube - How To Pull Request in 3 Minutes <https://www.youtube.com/watch?v=jRLGobWwA3Y>`_

Documentation
.............

The documentation is written in `reStructuredText<https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html#external-links>`. The files are located in PiFinders GitHub repository under ``docs\*.rst``. Many open source projects use `redthedocs.io <eadthedocs.io>` for creating documentation since it is emediatally generated, when you are commiting the GitHub code (CI/CD pipline). It is very easy to link your fork of the documentation code to GitHub. 


Setup the development environment
---------------------------------

PiFinder runs on an using:

* Version 3.9 or 3.10 python with a working `pip tool chain <https://pypi.org/project/pip/>`_
* Debian Buster (Bookworm to come)

Install python dependencies
...........................

For running PiFinder, you need to install some python libraries in certain versions. These lists can be installed via `pip tool chain <https://pypi.org/project/pip/>`_  and are separeted in two files: one for getting PiFinder to run, one for development purposes:

.. code-block::

    pip install -r requirements.txt
    pip install -r requirements_dev.txt


Install the Hipparcos catalog
.............................

The `hipparcos catalog <https://www.cosmos.esa.int/web/hipparcos>` will be downloaded to the following location: ``/home/pifinder/PiFinder/astro_data/``

.. code-block::

    wget -O /home/pifinder/PiFinder/astro_data/hip_main.dat https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat

Tetra3 solver
...........................

The `Tetra3 Solver <https://github.com/esa/tetra3>` is a "fast lost-in-space plate solver for star trackers written in Python". It is the next gen solver, that PiFinder uses.

.. code-block::

    cd python/PiFinder
    git clone https://github.com/esa/tetra3.git

Debugging from the command line
-------------------------------

If you installed all dependencies, you like to develop and test your code with debugging informations and all error messages. Or just to be able to stop an run the program. Therefore, switch to the ``~/PiFinder/python`` folder and start the PiFinder python program with certain command line parameters. 

.. code-block::

    cd /home/pifinder/PiFinder/python
    python3 -m **PiFinder.main** **[command line parameters]**

You simply stop the program with "Ctrl + C".

.. note::

Before you can start PiFinder, you have to stop all running PiFinder instances. PiFinder is designed to automatically start after boot. You can do this e.g. with awk:

.. code-block::

    ps aux | grep PiFinder.main | awk '{system("kill -9  " $2)}'

-h, --help - available command line arguments
.............................................

Look at the options with the "Help" flag 

.. note::

   The avaiable flags may change with forthcomming releases. Always refer to the real output.

.. code-block::

    pifinder@pifinder:~/PiFinder/python $ python3 -m PiFinder.main -h
    Starting PiFinder ...
    usage: main.py [-h] [-fh] [-c CAMERA] [-k KEYBOARD] [--script SCRIPT] [-f] [-n] [-x] [-l]
    
    eFinder
    
    optional arguments:
      -h, --help            show this help message and exit
      -fh, --fakehardware   Use a fake hardware for imu, gps
      -c CAMERA, --camera CAMERA
                            Specify which camera to use: pi, asi, debug or none
      -k KEYBOARD, --keyboard KEYBOARD
                            Specify which keyboard to use: pi, local or server
      --script SCRIPT       Specify a testing script to run
      -f, --fps             Display FPS in title bar
      -n, --notmp           Don't use the /dev/shm temporary directory. (usefull if not on pi)
      -x, --verbose         Set logging to debug mode
      -l, --log             Log to file

-x, --verbose - debug information
.................................

You can "enable debug information" simply by passing the '-x' flag:

.. code-block::

    pifinder@pifinder:~/PiFinder/python $ python3 -m PiFinder.main  -x
    Starting PiFinder ...
    2024-03-17 11:31:26,285 root: DEBUG using pi camera
    2024-03-17 11:31:26,383 PiFinder.manager_patch: DEBUG Patching multiprocessing.managers.AutoProxy to add manager_owned
    2024-03-17 11:31:26,431 root: DEBUG Ui state in main is{'observing_list': [], 'history_list': [], 'active_list': [], 'target': None, 'message_timeout': 0}
    Write: Starting....
    Write:    GPS
    Write:    Keyboard
    2024-03-17 11:31:28,544 root: DEBUG GPS waking
    [...]


-c CAMERA, --camera CAMERA
..........................

Use the "fake" camera module, so the PiFinder cam ist physically not necesary for testing purposes. Else specify which camera to use: pi, asi, debug or none.

.. code-block::

    python3 -m PiFinder.main -k local --camera debug -x

-fh, --fakehardware (imu, gps only)
...................................

This uses fake hardware for the imu and gps:

.. code-block::

    python3 -m PiFinder.main -fh -k local --camera debug -x


-k KEYBOARD, --keyboard KEYBOARD
................................

.. ATTENTION::

  Usage unclear

You can use either your the keyboard of the pi, the local keyboard. 



.. code-block::

    python3 -m PiFinder.main -fh -k server --camera debug -x


Troubleshooting
---------------

My app crashes
..............

When crashing, there are many unrelated stack traces running. Search for the relevant one. The rest is not important, these are the other threads stopping.

My IMU seems not to be working
..............................

First power up the unit and look at the Status page while moving it around. The status screen is part of the `Utility Screens <https://github.com/apos/PiFinder/blob/release_doc_updates/docs/source/user_guide.rst#utility-screens>`

.. image:: images/user_guide/STATUS_001_docs.png

If the IMU section is empty ("- -") or does not move, it is likely, that either the IMU is defect or you have a defect on your board.

1. Please check, if the board is soldered correctly and you have all pins fully soldered and did not shorten anything. 
2. If you sourced the parts by you own, it might be, that you bought the wrong IMU hardware version. You need the 4646 versio. On the non-stemma QT versions, the data pins are switched (`see here <https://discord.com/channels/1087556380724052059/1112859631702781992/1183859911982055525>`). 

If the IMU is defect, this only can be tested by removing it an replacing it with another

The demo mode - it is cloudy, but I like to test my PiFinder anyways
....................................................................

Getting a demo mode is to be able to run the PiFinder and almost all it's functionality not under the stars. Therefore the PiFinder get's an image from the disc and uses it for the screen. You can use all PiFinder commands, like searching for an object, you see the IMU run and you get a "fake" GPS signal. You also can check the PiFinder keyboard and the complete menu cycle. 

The way to get this funktionality, is to enter PiFinder in the 'test' or 'debug' mode.

First method: Press "ENT-A" to cycle through the screens to get to the Console screen and then press the "0" key. This will supply a fake GPS lock, time and cause the PiFinder to just solve an image from disk.  But it will respond to IMU movement and allow use of things like Push-To and all the other functions that require a solve/lock.
Second method: run PiFinder in tehe 



.. image:: images/user_guide/DEMO_MODE_001_docs.png

.. image:: images/user_guide/DEMO_MODE_002_docs.png



