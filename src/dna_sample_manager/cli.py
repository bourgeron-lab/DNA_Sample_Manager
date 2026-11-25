"""Command-line interface for dna-sample-manager."""

import logging
import threading
import webbrowser
from pathlib import Path
from typing import Annotated, Optional

import typer
from waitress import serve

from dna_sample_manager.backup import (
    DEFAULT_INTERVAL_HOURS, DEFAULT_KEEP, backup_database, list_backups, start_periodic_backups,
)

# En-têtes transmis par nginx (deploy/nginx-dna-sample-manager.conf)
PROXY_HEADERS = {"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"}


def waitress_options(host: str, port: int, threads: int, behind_proxy: bool) -> dict:
    """Options du serveur waitress.

    Par défaut, waitress SUPPRIME les en-têtes X-Forwarded-* : derrière nginx, l'app se
    croirait alors en HTTP (protection CSRF stricte de HTTPS désactivée, IP clientes = 127.0.0.1).
    En mode proxy, on ne fait confiance à ces en-têtes que s'ils viennent de 127.0.0.1.
    """
    opts = dict(host=host, port=port, threads=threads, ident="dna-sample-manager")
    if behind_proxy:
        opts.update(trusted_proxy="127.0.0.1", trusted_proxy_count=1,
                    trusted_proxy_headers=set(PROXY_HEADERS), clear_untrusted_proxy_headers=True)
    return opts


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
    behind_proxy: Annotated[
        bool,
        typer.Option("--behind-proxy",
                     help="Servi derrière un reverse proxy HTTPS (nginx) sur la même machine : "
                          "en-têtes X-Forwarded-* acceptés s'ils viennent de 127.0.0.1, "
                          "cookies réservés à HTTPS."),
    ] = False,
    open_browser: Annotated[
        bool,
        typer.Option("--open-browser/--no-browser", help="Ouvrir le navigateur au démarrage"),
    ] = True,
    threads: Annotated[
        int,
        typer.Option("--threads", min=1, max=64, help="Nombre de requêtes traitées en parallèle"),
    ] = 8,
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

    if behind_proxy and host not in ("127.0.0.1", "localhost", "::1"):
        typer.echo(f"ATTENTION — --behind-proxy avec --host {host} : l'app serait joignable sans "
                   "passer par nginx (donc sans HTTPS). Utilisez --host 127.0.0.1.", err=True)

    flask_app = create_app(db_path=db_path, behind_proxy=behind_proxy)

    if open_browser:
        # Ouvrir le navigateur après un court délai (le temps que le serveur démarre)
        url = f"http://{host}:{port}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # Serveur WSGI de production (multi-thread, un seul processus : adapté à SQLite,
    # et le thread de sauvegarde tourne dans ce même processus)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    serve(flask_app, **waitress_options(host, port, threads, behind_proxy))


if __name__ == "__main__":
    app()
