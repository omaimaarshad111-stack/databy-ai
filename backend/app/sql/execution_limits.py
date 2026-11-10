from dataclasses import dataclass
from threading import Lock
from uuid import UUID

from app.core.config import get_settings


@dataclass(frozen=True)
class ExecutionLimits:
    timeout_seconds: float
    default_page_size: int
    max_page_size: int
    max_offset: int
    max_columns: int
    max_result_bytes: int
    max_concurrent_per_user: int
    cache_ttl_seconds: int
    cache_max_bytes: int
    cache_max_entries: int

    @classmethod
    def from_settings(cls) -> "ExecutionLimits":
        settings = get_settings()
        return cls(
            timeout_seconds=settings.sql_execution_timeout_seconds,
            default_page_size=settings.sql_execution_default_page_size,
            max_page_size=settings.sql_execution_max_page_size,
            max_offset=settings.sql_execution_max_offset,
            max_columns=settings.sql_execution_max_columns,
            max_result_bytes=settings.sql_execution_max_result_bytes,
            max_concurrent_per_user=settings.sql_execution_max_concurrent_per_user,
            cache_ttl_seconds=settings.sql_execution_result_cache_ttl_seconds,
            cache_max_bytes=settings.sql_execution_result_cache_max_bytes,
            cache_max_entries=settings.sql_execution_result_cache_max_entries,
        )


class TooManyConcurrentExecutionsError(Exception):
    pass


class UserExecutionLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active: dict[UUID, int] = {}

    def acquire(self, user_id: UUID, maximum: int) -> None:
        with self._lock:
            active = self._active.get(user_id, 0)
            if active >= maximum:
                raise TooManyConcurrentExecutionsError
            self._active[user_id] = active + 1

    def release(self, user_id: UUID) -> None:
        with self._lock:
            active = self._active.get(user_id, 0)
            if active <= 1:
                self._active.pop(user_id, None)
            else:
                self._active[user_id] = active - 1


user_execution_limiter = UserExecutionLimiter()
