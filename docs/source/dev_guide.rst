.. _dev_guide:

Developer Guide
===============

If you have questions about the software or would like to contribute feel free to open an issue or a pull request. Here you find additional informations:

* `GitHub Docs - About pull requests<https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests>`_
* `GitHub Docs - Creating a pull request<https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request>`_
* `Youtube - How To Pull Request in 3 Minutes<https://www.youtube.com/watch?v=jRLGobWwA3Y>`_

Getting the source
------------------

If you are serious about contributing, best is to fork the code on github
into your own project

Environment
------------------

PiFinder needs 3.9 or 3.10 python with a working pip

Setup
------------------

Install python dependencies
...........................

```
pip install -r requirements.txt
pip install -r requirements_dev.txt
```

Install other dependencies
...........................

Hipparcos catalog
...........................

Download the hipparcos catalog, change the download location.

```wget -O /home/pifinder/PiFinder/astro_data/hip_main.dat https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat```

Tetra3 solver
...........................

```
cd python/PiFinder
git clone https://github.com/esa/tetra3.git
```

Running
-------

Run the following command from the ./python folder
```python3 -m PiFinder.main -fh -k server --camera debug -x```


Debugging
---------

You can enable debug information by passing the '-x' flag

When crashing, there are many unrelated stack traces, search for the relevant
one, the rest are the other threads stopping.

