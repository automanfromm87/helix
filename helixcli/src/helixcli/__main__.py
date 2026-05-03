"""Allow `python -m helixcli ...` to work without a console-script entry."""
from helixcli.cli import app

if __name__ == "__main__":
    app()
