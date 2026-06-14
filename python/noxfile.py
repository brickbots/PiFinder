import nox

nox.options.sessions = ["lint", "format", "type_hints", "smoke_tests"]


@nox.session(reuse_venv=True, python="3.9")
def lint(session: nox.Session) -> None:
    """
    Lint the project's codebase.

    This session installs necessary dependencies for linting and then runs the linter to check for
    stylistic errors and coding standards compliance across the project's codebase.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    session.install("ruff==0.4.8")
    session.run("ruff", "check", "--fix", "--config", "builtins=['_']")


@nox.session(reuse_venv=True, python="3.9")
def format(session: nox.Session) -> None:
    """
    Format the project's codebase.

    This session installs necessary dependencies for code formatting and runs the formatter
    to check (and optionally correct) the code format according to the project's style guide.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    session.install("ruff==0.4.8")
    session.run("ruff", "format")


@nox.session(reuse_venv=True, python="3.9")
def type_hints(session: nox.Session) -> None:
    """
    Check type hints in the project's codebase.

    This session installs necessary dependencies for type checking and runs a static type checker
    to validate the type hints throughout the project's codebase, ensuring they are correct and consistent.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    session.install("-r", "requirements.txt")
    session.install("-r", "requirements_dev.txt")
    # First run populates the cache so --install-types knows what stubs are needed.
    # success_codes=[0, 1] here is expected: missing-stub errors before stubs are
    # installed. The second run (with stubs) must exit 0; real type errors fail CI.
    # Targets PiFinder/ explicitly to avoid broken tetra3 symlink in the tree.
    session.run("mypy", "PiFinder", success_codes=[0, 1])
    session.run("mypy", "--install-types", "--non-interactive", "PiFinder")


@nox.session(reuse_venv=True, python="3.9")
def unit_tests(session: nox.Session) -> None:
    """
    Run the project's unit tests.

    This session installs the necessary dependencies and runs the project's unit tests.
    It is focused on testing the functionality of individual units of code in isolation.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    session.install("-r", "requirements.txt")
    session.install("-r", "requirements_dev.txt")
    session.run("pytest", "-m", "unit")


@nox.session(reuse_venv=True, python="3.9")
def web_tests(session: nox.Session) -> None:
    """
    Run the project's test suite on the web interface.

    This session installs the necessary dependencies and tests the web interface using Selenium.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    session.install("-r", "requirements.txt")
    session.install("-r", "requirements_dev.txt")
    session.run("pytest", "-m", "web")


@nox.session(reuse_venv=True, python="3.9")
def smoke_tests(session: nox.Session) -> None:
    """
        Run the project's smoke tests.
    nox
        This session installs the necessary dependencies and runs a subset of tests designed to quickly
        check the most important functions of the program, often as a prelude to more thorough testing.

        Args:
            session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    session.install("-r", "requirements.txt")
    session.install("-r", "requirements_dev.txt")
    session.run("pytest", "-m", "smoke")


@nox.session(reuse_venv=True, python="3.9")
def ui_tests(session: nox.Session) -> None:
    """
    Run the UI module smoke harness (tests/test_ui_modules.py).

    Constructs every UI screen through a real MenuManager and exercises its
    key_* methods (crash-only smoke). Builds the real catalogs and, for
    chart/align, may download hip_main.dat on first run. Heavier and more
    network-dependent than the unit suite, so it lives in its own session.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    session.install("-r", "requirements.txt")
    session.install("-r", "requirements_dev.txt")
    session.run("pytest", "-m", "integration", "tests/test_ui_modules.py")


@nox.session(reuse_venv=True, python="3.9")
def babel(session: nox.Session) -> None:
    """
    Run the I18N toolchain
    """
    session.install("-r", "requirements.txt")
    session.install("-r", "requirements_dev.txt")

    session.run(
        "pybabel",
        "extract",
        "-F",
        "babel.cfg",
        "-c",
        "TRANSLATORS",
        "-o",
        "locale/messages.pot",
        "./PiFinder",
    )
    session.run("pybabel", "update", "-i", "locale/messages.pot", "-d", "locale")
    session.run("pybabel", "compile", "-d", "locale")
