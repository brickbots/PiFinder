import nox

nox.options.sessions = ["lint", "format", "type_hints", "smoke_tests"]


@nox.session(python=False)
def lint(session: nox.Session) -> None:
    """Lint the project's codebase."""
    session.run("ruff", "check", "--fix", "--config", "builtins=['_']")


@nox.session(python=False)
def format(session: nox.Session) -> None:
    """Format the project's codebase."""
    session.run("ruff", "format")


@nox.session(python=False)
def type_hints(session: nox.Session) -> None:
    """Check type hints in the project's codebase."""
    session.run("mypy", "--install-types", "--non-interactive", ".")


@nox.session(python=False)
def unit_tests(session: nox.Session) -> None:
    """Run the project's unit tests."""
    session.run("pytest", "-m", "unit")


@nox.session(python=False)
def smoke_tests(session: nox.Session) -> None:
    """Run the project's smoke tests."""
    session.run("pytest", "-m", "smoke")


@nox.session(python=False)
def babel(session: nox.Session) -> None:
    """Run the I18N toolchain."""
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
