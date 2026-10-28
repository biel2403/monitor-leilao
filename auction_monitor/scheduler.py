from __future__ import annotations

import logging
import threading
import time

from auction_monitor.service import MonitorService

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, service: MonitorService, interval_seconds: int):
        self.service = service
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                stats = self.service.run_once()
                logger.info("Ciclo concluido: %s", stats)
            except Exception:
                logger.exception("Falha no ciclo agendado")
            self._stop.wait(self.interval_seconds)

