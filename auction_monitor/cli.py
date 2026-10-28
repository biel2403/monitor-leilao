from __future__ import annotations

import argparse
import json
import logging
import sys

from auction_monitor.api import ApiServer
from auction_monitor.config import load_settings
from auction_monitor.database import Database
from auction_monitor.fipe import FipeClient
from auction_monitor.scheduler import Scheduler
from auction_monitor.service import MonitorService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitoramento de leiloes online")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Cria ou atualiza o banco")
    sub.add_parser("run-once", help="Executa uma coleta")
    sub.add_parser("serve", help="Inicia API, painel e agendador")
    add_filter = sub.add_parser("add-filter", help="Cria filtro a partir de JSON")
    add_filter.add_argument("json_payload")
    fipe_test = sub.add_parser("fipe-test", help="Consulta uma versao na API FIPE sem alterar os lotes")
    fipe_test.add_argument("brand")
    fipe_test.add_argument("model")
    fipe_test.add_argument("year")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    db = Database(settings.database_path)
    service = MonitorService(settings, db)

    if args.command == "fipe-test":
        try:
            result = FipeClient(settings.fipe_api_token).vehicle(args.brand, args.model, args.year)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "init-db":
        db.migrate()
        print(f"Banco pronto em {settings.database_path}")
        return 0
    if args.command == "run-once":
        stats = service.run_once()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    if args.command == "add-filter":
        db.migrate()
        payload = json.loads(args.json_payload)
        filter_id = db.create_filter(
            payload["name"],
            payload.get("criteria") or {},
            payload.get("channels") or ["telegram"],
            bool(payload.get("active", True)),
        )
        print(filter_id)
        return 0
    if args.command == "serve":
        db.migrate()
        scheduler = Scheduler(service, settings.scrape_interval_seconds)
        scheduler.start()
        ApiServer(settings, db, service).serve()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
