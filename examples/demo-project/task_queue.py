"""A tiny in-process task queue with worker threads and retry support."""

import queue
import threading
import time
import traceback
from dataclasses import dataclass, field


@dataclass
class Task:
    fn: object
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    retries_left: int = 2
    delay: float = 0.0


class TaskQueue:
    """Run callables on a pool of daemon workers.

    Failed tasks are retried with exponential backoff until
    `retries_left` reaches zero. The queue is deliberately
    dependency-free so it can be dropped into any project.
    """

    def __init__(self, workers=4):
        self._queue = queue.PriorityQueue()
        self._workers = []
        self._seq = 0
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        for i in range(workers):
            t = threading.Thread(target=self._run, name=f"worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

    def submit(self, fn, *args, retries=2, delay=0.0, **kwargs):
        """Schedule `fn(*args, **kwargs)`; returns immediately."""
        with self._lock:
            self._seq += 1
            seq = self._seq
        task = Task(fn=fn, args=args, kwargs=kwargs, retries_left=retries, delay=delay)
        self._queue.put((time.monotonic() + delay, seq, task))

    def _run(self):
        while not self._stopped.is_set():
            try:
                run_at, _, task = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            wait = run_at - time.monotonic()
            if wait > 0:
                self._stopped.wait(wait)
            try:
                task.fn(*task.args, **task.kwargs)
            except Exception:
                traceback.print_exc()
                if task.retries_left > 0:
                    task.retries_left -= 1
                    backoff = min(2 ** (3 - task.retries_left), 30)
                    self.submit(task.fn, *task.args, retries=task.retries_left,
                                delay=backoff, **task.kwargs)
            finally:
                self._queue.task_done()

    def join(self):
        """Block until every queued task has finished."""
        self._queue.join()

    def shutdown(self):
        self._stopped.set()
        for t in self._workers:
            t.join(timeout=1)
