import logging
import queue
import threading
from datetime import datetime

from app.database import Account, EmailAlias, RegistrationTask, SessionLocal
from app.services.token_service import replace_account_tokens


logger = logging.getLogger(__name__)
MAX_CONCURRENT_REGISTRATIONS = 3


def _format_log_line(message: str) -> str:
    timestamp = datetime.now().strftime("%H:%M:%S")
    return f"[{timestamp}] {message}"


def _append_task_log(db, task: RegistrationTask, message: str, *, timestamped: bool = False) -> None:
    line = message if timestamped else _format_log_line(message)
    task.log = f"{task.log}\n{line}" if task.log else line
    task.updated_at = datetime.utcnow()
    db.commit()


def _access_token_expires_at(result: dict) -> datetime | None:
    from app.services import registration_service

    return registration_service.oauth_access_token_expires_at(result)


class RegistrationTaskManager:
    def __init__(self, max_workers: int = MAX_CONCURRENT_REGISTRATIONS):
        self.max_workers = max_workers
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self.recover_stale_tasks()
            self._start_workers()
            logger.info("registration task manager started with %s workers", self.max_workers)

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._stop_event.set()
            for _ in self._threads:
                self._queue.put(None)
            threads = list(self._threads)
            self._threads = []
            self._started = False
        for thread in threads:
            thread.join(timeout=1)

    def enqueue(self, task_id: int) -> None:
        if not self._started:
            with self._lock:
                if not self._started:
                    self._start_workers()
        self._queue.put(task_id)

    def recover_stale_tasks(self) -> None:
        db = SessionLocal()
        try:
            tasks = (
                db.query(RegistrationTask)
                .filter(RegistrationTask.status.in_(("queued", "running")))
                .all()
            )
            for task in tasks:
                task.status = "failed"
                _append_task_log(db, task, "系统检测到进程中断，任务已标记失败，可手动重试。")
            if tasks:
                logger.warning("recovered %s stale registration tasks", len(tasks))
        finally:
            db.close()

    def _worker_loop(self) -> None:
        while True:
            task_id = self._queue.get()
            try:
                if task_id is None:
                    return
                self._run_task(task_id)
            except Exception:
                logger.exception("registration worker crashed")
            finally:
                self._queue.task_done()

    def _start_workers(self) -> None:
        self._stop_event.clear()
        self._threads = []
        for index in range(self.max_workers):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"registration-worker-{index + 1}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        self._started = True

    def _run_task(self, task_id: int) -> None:
        from app.services import registration_service

        db = SessionLocal()
        try:
            task = db.query(RegistrationTask).filter(RegistrationTask.id == task_id).first()
            if not task or task.status != "queued":
                return

            task.status = "running"
            task.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(task)

            def persist_log(line: str) -> None:
                _append_task_log(db, task, line, timestamped=True)

            try:
                result = registration_service.register_account(task.email, log_sink=persist_log)
                if result["success"]:
                    existing = db.query(Account).filter(Account.email == result["email"]).first()
                    if existing:
                        persist_log(f"  ❌ 邮箱 {result['email']} 已存在，跳过入库")
                        task.status = "failed"
                        task.updated_at = datetime.utcnow()
                        db.commit()
                        return

                    acc = Account(
                        email=result["email"],
                        password=result["password"],
                        session_token=result.get("session_token"),
                        access_token=result.get("access_token"),
                        token_expires_at=_access_token_expires_at(result),
                        status="active",
                        cf_email_alias=task.email,
                    )
                    db.add(acc)
                    db.commit()
                    db.refresh(acc)

                    replace_account_tokens(
                        db,
                        acc,
                        {
                            "access_token": (result.get("access_token"), _access_token_expires_at(result)),
                            "refresh_token": (result.get("refresh_token"), None),
                            "id_token": (result.get("id_token"), None),
                            "session_token": (result.get("session_token"), None),
                        },
                    )

                    alias = db.query(EmailAlias).filter(EmailAlias.alias == task.email).first()
                    if alias:
                        alias.is_used = True
                        alias.account_id = acc.id

                    task.status = "done"
                    task.account_id = acc.id
                else:
                    task.status = "failed"
            except Exception as exc:
                task.status = "failed"
                _append_task_log(db, task, f"[Error] {exc}")

            task.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()


registration_task_manager = RegistrationTaskManager()
