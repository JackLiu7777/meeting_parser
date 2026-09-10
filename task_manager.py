import asyncio
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    GENERATING_COMPLIANCE_PLAN = "generating_compliance_plan"
    COMPLIANCE_PLAN_DONE = "compliance_plan_done"
    GENERATING_DOCUMENT_LIST = "generating_document_list"
    DOCUMENT_LIST_DONE = "document_list_done"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


TASK_PROGRESS = {
    TaskStatus.PENDING: "任务已提交，等待处理",
    TaskStatus.GENERATING_COMPLIANCE_PLAN: "正在生成合规计划书",
    TaskStatus.COMPLIANCE_PLAN_DONE: "合规计划书生成完成",
    TaskStatus.GENERATING_DOCUMENT_LIST: "正在生成文书清单",
    TaskStatus.DOCUMENT_LIST_DONE: "文书清单生成完成",
    TaskStatus.COMPLETED: "处理完成",
    TaskStatus.FAILED: "处理失败",
    TaskStatus.SUPERSEDED: "任务已被新的提交覆盖",
}

TERMINAL_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.SUPERSEDED,
}


class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, dict] = {}
        self.latest_tasks: Dict[tuple[str, str], str] = {}
        self.write_locks: Dict[tuple[str, str], asyncio.Lock] = {}
        self.subscribers: Dict[str, set[asyncio.Queue]] = {}

    def _task_key(self, meeting_id: str, order_id: str) -> tuple[str, str]:
        return (meeting_id, order_id)

    def _snapshot(self, task_id: str) -> Optional[dict]:
        task = self.tasks.get(task_id)
        if not task:
            return None
        data = task.copy()
        status = data.get("status")
        if isinstance(status, TaskStatus):
            data["status"] = status.value
        return data

    def _broadcast(self, task_id: str):
        snapshot = self._snapshot(task_id)
        if not snapshot:
            return
        for queue in list(self.subscribers.get(task_id, set())):
            queue.put_nowait(snapshot)

    def create_task(self, meeting_id: str, order_id: str) -> str:
        """Create a new task and mark it as the latest task for this business key."""
        task_key = self._task_key(meeting_id, order_id)
        previous_task_id = self.latest_tasks.get(task_key)
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()

        self.tasks[task_id] = {
            "task_id": task_id,
            "meeting_id": meeting_id,
            "order_id": order_id,
            "status": TaskStatus.PENDING,
            "progress": TASK_PROGRESS[TaskStatus.PENDING],
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        self.latest_tasks[task_key] = task_id

        if previous_task_id and previous_task_id in self.tasks:
            self.set_superseded(previous_task_id, task_id)

        return task_id

    def update_task(self, task_id: str, **kwargs):
        """Update task fields and broadcast the latest snapshot."""
        if task_id in self.tasks:
            kwargs["updated_at"] = datetime.now().isoformat()
            self.tasks[task_id].update(kwargs)
            self._broadcast(task_id)

    def get_task(self, task_id: str) -> Optional[dict]:
        """Get task info."""
        return self._snapshot(task_id)

    def subscribe(self, task_id: str) -> Optional[asyncio.Queue]:
        """Subscribe to task status updates and receive the latest snapshot first."""
        if task_id not in self.tasks:
            return None
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.setdefault(task_id, set()).add(queue)
        snapshot = self._snapshot(task_id)
        if snapshot:
            queue.put_nowait(snapshot)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue):
        """Remove a task status subscriber."""
        queues = self.subscribers.get(task_id)
        if not queues:
            return
        queues.discard(queue)
        if not queues:
            self.subscribers.pop(task_id, None)

    def is_terminal_status(self, status: str | TaskStatus) -> bool:
        return status in TERMINAL_STATUSES or status in {item.value for item in TERMINAL_STATUSES}

    def is_latest_task(self, task_id: str, meeting_id: str, order_id: str) -> bool:
        """Return whether this task is still the latest one for the business key."""
        return self.latest_tasks.get(self._task_key(meeting_id, order_id)) == task_id

    def get_write_lock(self, meeting_id: str, order_id: str) -> asyncio.Lock:
        """Get the per-business-key write lock used for OSS and DB updates."""
        task_key = self._task_key(meeting_id, order_id)
        if task_key not in self.write_locks:
            self.write_locks[task_key] = asyncio.Lock()
        return self.write_locks[task_key]

    def set_status(self, task_id: str, status: TaskStatus, progress: str = None, **kwargs):
        """Set task status and broadcast it to SSE subscribers."""
        current_status = self.tasks.get(task_id, {}).get("status")
        if current_status == TaskStatus.SUPERSEDED and status != TaskStatus.SUPERSEDED:
            return
        data = {
            "status": status,
            "progress": progress or TASK_PROGRESS[status],
        }
        data.update(kwargs)
        self.update_task(task_id, **data)

    def set_completed(self, task_id: str, result: dict):
        """Mark task as completed."""
        if self.tasks.get(task_id, {}).get("status") == TaskStatus.SUPERSEDED:
            return
        self.set_status(task_id, TaskStatus.COMPLETED, result=result)

    def set_failed(self, task_id: str, error: str):
        """Mark task as failed."""
        if self.tasks.get(task_id, {}).get("status") == TaskStatus.SUPERSEDED:
            return
        self.set_status(task_id, TaskStatus.FAILED, error=error)

    def set_superseded(self, task_id: str, superseded_by: str = None):
        """Mark task as superseded by a later submission."""
        self.set_status(
            task_id,
            TaskStatus.SUPERSEDED,
            superseded_by=superseded_by,
            superseded_at=datetime.now().isoformat(),
        )


task_manager = TaskManager()
