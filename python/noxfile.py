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
    session.run("mypy", "--install-types", "--non-interactive", ".")


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
def babel(session: nox.Session) -> None:
    """
    Run the I18N toolchain
    """
    session.install("-r", "requirements.txt")
    session.install("-r", "requirements_dev.txt")

    session.run(
        "pybabel",
        "extract",
        "-c",
        "TRANSLATORS",
        "-o",
        "locale/messages.pot",
        "./PiFinder",
    )
    session.run("pybabel", "update", "-i", "locale/messages.pot", "-d", "locale")
    session.run("pybabel", "compile", "-d", "locale")
