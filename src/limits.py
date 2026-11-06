import threading
import time
from collections import deque
from contextlib import contextmanager


class Busy(ValueError):
    pass


class Governor:
    """Límites por proceso, no una garantía de identidad ni un contador financiero remoto."""
    def __init__(self):
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)
        self.active = set()
        self.usage = {}
        self.reserved = 0.0
        self.credit_blocked = False

    @contextmanager
    def turn(self, session, ai=False, budget=0.0, reserve=0.05, clock=time.time):
        now = clock()
        with self.lock:
            if session in self.active:
                raise Busy('Ya hay una consulta en curso en esta sesión.')
            # La memoria de cuotas no retiene preguntas ni identificadores de personas.
            self.usage = {k: deque(t for t in values if t > now - 3600) for k, values in self.usage.items() if values and values[-1] > now - 3600}
            recent = self.usage.get(session, deque())
            if ai:
                if self.credit_blocked:
                    raise Busy('IA temporalmente no disponible. Puedes usar la búsqueda por filtros.')
                if len(recent) >= 5:
                    raise Busy('Esta sesión alcanzó las 5 preguntas con IA por hora. Puedes usar los filtros.')
                if reserve <= 0 or self.reserved + reserve > budget:
                    raise Busy('Se alcanzó el límite preventivo de IA de esta ejecución. Puedes usar los filtros.')
            if not self.slots.acquire(blocking=False):
                raise Busy('Hay dos consultas en curso. Intenta nuevamente en un momento.')
            self.active.add(session)
            if ai:
                recent.append(now)
                self.usage[session] = recent
                self.reserved += reserve
        try:
            yield
        finally:
            with self.lock:
                self.active.discard(session)
                self.slots.release()

    def stop_ai(self):
        with self.lock:
            self.credit_blocked = True

    def ai_available(self, budget, reserve=0.05):
        with self.lock:
            return not self.credit_blocked and reserve > 0 and self.reserved + reserve <= budget
