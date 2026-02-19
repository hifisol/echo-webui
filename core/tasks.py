import json
import subprocess
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from core.events import event_bus


class TaskRunner:
    def __init__(self, db_path, max_workers=4, buffer_lines=1000):
        self.db_path = db_path
        self.buffer_lines = buffer_lines
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs = {}
        self._lock = threading.Lock()

    def submit(self, tool_name, cmd_args, callback=None):
        job_id = str(uuid.uuid4())[:8]
        job = {
            "id": job_id,
            "tool": tool_name,
            "args": cmd_args,
            "status": "pending",
            "pid": None,
            "process": None,
            "output": deque(maxlen=self.buffer_lines),
            "exit_code": None,
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
            "callback": callback,
        }
        with self._lock:
            self._jobs[job_id] = job

        self._persist_job(job)
        event_bus.publish("jobs", "job-update", self._job_summary(job))
        self.executor.submit(self._run, job_id)
        return job_id

    def _run(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return

        job["status"] = "running"
        job["started_at"] = time.time()
        self._persist_job(job)
        event_bus.publish("jobs", "job-update", self._job_summary(job))

        try:
            proc = subprocess.Popen(
                job["args"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            job["process"] = proc
            job["pid"] = proc.pid
            self._persist_job(job)

            for line in proc.stdout:
                line = line.rstrip("\n")
                job["output"].append(line)
                event_bus.publish("jobs", "log-line", {
                    "job_id": job_id,
                    "line": line,
                })

            proc.wait()
            job["exit_code"] = proc.returncode
            job["status"] = "completed" if proc.returncode == 0 else "failed"
        except Exception as e:
            job["output"].append(f"ERROR: {e}")
            job["status"] = "failed"
            job["exit_code"] = -1

        job["completed_at"] = time.time()
        job["process"] = None
        self._persist_job(job)
        event_bus.publish("jobs", "job-update", self._job_summary(job))

        if job.get("callback"):
            try:
                job["callback"](job)
            except Exception:
                pass

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or not job.get("process"):
                return False

        try:
            job["process"].terminate()
            job["process"].wait(timeout=5)
        except subprocess.TimeoutExpired:
            job["process"].kill()
        except Exception:
            pass

        job["status"] = "cancelled"
        job["completed_at"] = time.time()
        job["process"] = None
        self._persist_job(job)
        event_bus.publish("jobs", "job-update", self._job_summary(job))
        return True

    def get_job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return None
        summary = self._job_summary(job)
        summary["output"] = list(job["output"])
        return summary

    def list_jobs(self, status=None):
        with self._lock:
            jobs = list(self._jobs.values())
        results = []
        for job in sorted(jobs, key=lambda j: j["created_at"], reverse=True):
            if status and job["status"] != status:
                continue
            results.append(self._job_summary(job))
        return results

    def _job_summary(self, job):
        return {
            "id": job["id"],
            "tool": job["tool"],
            "args": job["args"] if isinstance(job["args"], str) else " ".join(job["args"]),
            "status": job["status"],
            "pid": job["pid"],
            "exit_code": job["exit_code"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
        }

    def _persist_job(self, job):
        import sqlite3
        import os
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT OR REPLACE INTO jobs
                   (id, tool, args, status, pid, exit_code, output_tail, created_at, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime(?, 'unixepoch'), datetime(?, 'unixepoch'), datetime(?, 'unixepoch'))""",
                (
                    job["id"],
                    job["tool"],
                    json.dumps(job["args"]) if not isinstance(job["args"], str) else job["args"],
                    job["status"],
                    job["pid"],
                    job["exit_code"],
                    "\n".join(job["output"]) if job["output"] else "",
                    job["created_at"],
                    job["started_at"],
                    job["completed_at"],
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
