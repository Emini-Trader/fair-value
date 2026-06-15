"""Entry point so ``python -m fairvalue`` runs the CLI."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
