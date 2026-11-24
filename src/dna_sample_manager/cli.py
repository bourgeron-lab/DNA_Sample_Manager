"""Command-line interface for dna-sample-manager."""

import threading
import webbrowser
from pathlib import Path
from typing import Annotated, Optional

import typer

from dna_sample_manager.backup import (
    DEFAULT_INTERVAL_HOURS, DEFAULT_KEEP, backup_database, list_backups, start_periodic_backups,
)

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
    backup_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--backup-dir",
            help="Dossier des sauvegardes (défaut : <dossier de la base>/backups). "
                 "Idéalement sur un autre disque que la base.",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    keep: Annotated[
        int,
        typer.Option("--keep", min=1, help="Nombre de sauvegardes conservées (les plus anciennes sont supprimées)"),
    ] = DEFAULT_KEEP,
    backup_interval: Annotated[
        float,
        typer.Option("--backup-interval", min=0.1, help="Intervalle entre deux sauvegardes automatiques, en heures"),
    ] = DEFAULT_INTERVAL_HOURS,
    no_backup: Annotated[
        bool,
        typer.Option("--no-backup", help="Désactive les sauvegardes automatiques (démarrage + périodiques)"),
    ] = False,
    backup_only: Annotated[
        bool,
        typer.Option("--backup-only", help="Fait une sauvegarde puis quitte, sans démarrer le serveur"),
    ] = False,
) -> None:
    """Démarre l'application DNA Sample Manager.

    Par défaut, la base est sauvegardée au démarrage puis toutes les 24 h
    dans <dossier de la base>/backups (30 dernières conservées).
    """
    # Accepte un fichier .db directement ou un dossier contenant dna_samples.db
    if db.is_dir():
        db_path = db / "dna_samples.db"
    else:
        db_path = db

    if backup_only:
        try:
            dest = backup_database(db_path, backup_dir, keep)
        except Exception as e:
            typer.echo(f"ERREUR de sauvegarde : {e}", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"Sauvegarde : {dest}")
        typer.echo(f"{len(list_backups(db_path, backup_dir))} sauvegarde(s) dans {dest.parent}")
        return

    from dna_sample_manager.app import create_app

    typer.echo(f"DNA Sample Manager v0.1.0")
    typer.echo(f"Base de données : {db_path}")
    typer.echo(f"Serveur : http://{host}:{port}")

    # Sauvegarde AVANT create_app (qui peut modifier le schéma : création de tables)
    if no_backup:
        typer.echo("Sauvegardes automatiques : désactivées (--no-backup)")
    elif db_path.is_file():
        try:
            dest = backup_database(db_path, backup_dir, keep)
            typer.echo(f"Sauvegarde : {dest}  (puis toutes les {backup_interval:g} h, {keep} conservées)")
        except Exception as e:
            # Une sauvegarde ratée ne doit pas empêcher de travailler, mais doit se voir
            typer.echo(f"ATTENTION — sauvegarde au démarrage impossible : {e}", err=True)
        start_periodic_backups(db_path, backup_dir, keep, backup_interval,
                               log=lambda msg: typer.echo(msg, err=msg.startswith("ERREUR")))
    typer.echo("=" * 50)

    flask_app = create_app(db_path=db_path)

    # Ouvrir le navigateur après un court délai (le temps que Flask démarre)
    url = f"http://{host}:{port}"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    flask_app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    app()
