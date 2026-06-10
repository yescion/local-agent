"""CLI entry point."""

from local_agent.cli.app import app


def cli_entry() -> None:
    app()


if __name__ == "__main__":
    cli_entry()
