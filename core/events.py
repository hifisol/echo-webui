import json
import queue
import threading
import time


class EventBus:
    def __init__(self):
        self._subscribers = {}
        self._lock = threading.Lock()

    def subscribe(self, channel):
        q = queue.Queue(maxsize=100)
        sub_id = id(q)
        with self._lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = {}
            self._subscribers[channel][sub_id] = q
        try:
            while True:
                try:
                    data = q.get(timeout=30)
                    yield data
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with self._lock:
                self._subscribers.get(channel, {}).pop(sub_id, None)

    def publish(self, channel, event_type, data):
        msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            subs = self._subscribers.get(channel, {})
            dead = []
            for sub_id, q in subs.items():
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(sub_id)
            for sub_id in dead:
                subs.pop(sub_id, None)


event_bus = EventBus()
