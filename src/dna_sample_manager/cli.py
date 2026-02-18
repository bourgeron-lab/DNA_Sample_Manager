"""Command-line interface for dna-sample-manager."""

import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="dna-sample-manager",
    help="Application web de gestion d'échantillons ADN.",
    add_completion=False,
)


@app.command()
def main(
    db: Annotated[
        Path,
        typer.Argument(
            help="Chemin vers la base de données (.db) ou vers un dossier contenant dna_samples.db",
            exists=True,
            readable=True,
            resolve_path=True,
        ),
    ],
    host: Annotated[
        str,
        typer.Option("--host", help="Adresse d'écoute du serveur"),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port du serveur"),
    ] = 5003,
) -> None:
    """Démarre l'application DNA Sample Manager."""
    from dna_sample_manager.app import create_app

    # Accepte un fichier .db directement ou un dossier contenant dna_samples.db
    if db.is_dir():
        db_path = db / "dna_samples.db"
    else:
        db_path = db

    typer.echo(f"DNA Sample Manager v0.1.0")
    typer.echo(f"Base de données : {db_path}")
    typer.echo(f"Serveur : http://{host}:{port}")
    typer.echo("=" * 50)

    flask_app = create_app(db_path=db_path)

    # Ouvrir le navigateur après un court délai (le temps que Flask démarre)
    url = f"http://{host}:{port}"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    flask_app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    app()
