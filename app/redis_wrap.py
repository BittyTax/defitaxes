import time
from typing import Optional, Tuple, Union

import redis

from .util import log, log_error


class Redis:
    KEY_QUEUE = "queue"
    KEY_PROGRESS = "progress"
    KEY_PROGRESS_ENTRY = "progress_entry"
    KEY_LAST_UPDATE = "last_update"
    KEY_RUNNING = "running"

    def __init__(self, address: str) -> None:
        self.R = redis.StrictRedis(host="localhost", decode_responses=True)
        self.address = address

    def enq(self) -> None:
        if self.qpos():
            return

        self.set(self.KEY_LAST_UPDATE, int(time.time()))
        self.R.rpush(self.KEY_QUEUE, self.address)

    def deq(self) -> None:
        self.R.lrem(self.KEY_QUEUE, 0, self.address)

    def qpos(self) -> Optional[int]:
        try:
            queue = self.R.lrange(self.KEY_QUEUE, 0, -1)
            return queue.index(self.address) + 1
        except ValueError:
            return None

    def wait_finish(self) -> bool:
        if self.get(self.KEY_RUNNING):
            qpos = self.qpos()
            if qpos and qpos > 1:
                self.wait_queue()

            while self.get(self.KEY_RUNNING):
                time.sleep(1)
            return True
        return False

    def is_running(self) -> bool:
        if self.get(self.KEY_RUNNING):
            return True
        return False

    def wait_queue(self) -> None:
        last_update_change = int(time.time())
        prev_top_last_update = None
        error_recorded = False

        pb = ProgressBar(self)

        top_address = self.R.lindex(self.KEY_QUEUE, 0)
        while top_address and top_address != self.address:
            qpos = self.qpos()
            if qpos and qpos > 1:
                top_progress = self.R.get(f"{top_address}_{self.KEY_PROGRESS}")
                pb.set(
                    f"Waiting for other users, your queue position: {qpos}, "
                    f"current user's progress: "
                    f"{min(100, float(top_progress) if top_progress else 0):0.2f}%",
                    0,
                )

                top_last_update = self.R.get(f"{top_address}_{self.KEY_LAST_UPDATE}")
                if not top_last_update or time.time() - int(top_last_update) > 30:
                    # assume it crashed
                    log("assuming other guy crashed", time.time(), top_last_update)
                    self.R.lrem(self.KEY_QUEUE, 0, top_address)

                if top_last_update != prev_top_last_update:
                    last_update_change = int(time.time())
                    prev_top_last_update = top_last_update

                if not error_recorded and time.time() - last_update_change > 600:
                    log_error(
                        "WAITING TOO LONG",
                        "address",
                        self.address,
                        "redis top",
                        top_address,
                        "top_last_update",
                        top_last_update,
                        "time diff",
                        time.time() - float(top_last_update) if top_last_update else 0,
                    )
                    error_recorded = True

            log("redis check in loop", top_address, self.address)
            time.sleep(1)
            top_address = self.R.lindex(self.KEY_QUEUE, 0)

    def set(self, key: str, val: Union[str, int, float]) -> None:
        self.R.set(f"{self.address}_{key}", val)

    def get(self, key: str) -> Optional[str]:
        return self.R.get(f"{self.address}_{key}")

    def unset(self, key: str) -> None:
        self.R.delete(f"{self.address}_{key}")

    def start(self) -> None:
        self.set(self.KEY_RUNNING, "1")
        self.unset(self.KEY_PROGRESS)
        self.unset(self.KEY_PROGRESS_ENTRY)
        self.unset(self.KEY_LAST_UPDATE)

    def finish(self) -> None:
        self.unset(self.KEY_RUNNING)

    def wipe(self) -> None:
        self.unset(self.KEY_PROGRESS)
        self.unset(self.KEY_PROGRESS_ENTRY)
        self.unset(self.KEY_LAST_UPDATE)
        self.unset(self.KEY_RUNNING)
        self.deq()

    def cleanup(self) -> None:
        current_time = int(time.time())

        for key in self.R.keys(f"*_{self.KEY_LAST_UPDATE}"):
            log("key", key)
            last_update = self.R.get(key)

            # Remove addresses that have not updated for 30 minutes
            if last_update and current_time - int(last_update) > 1800:
                address, _ = key.split("_", 1)
                to_delete = [
                    f"{address}_{self.KEY_PROGRESS}",
                    f"{address}_{self.KEY_PROGRESS_ENTRY}",
                    f"{address}_{self.KEY_RUNNING}",
                ]
                log("deleting redis keys", to_delete)
                self.R.delete(*to_delete)
                log("unqueueing ", address)
                self.R.lrem(self.KEY_QUEUE, 0, address)


class ProgressBar:
    def __init__(self, redis_instance: Redis) -> None:
        self.redis = redis_instance

    def update(self, entry: Optional[str] = None, percent_add: Optional[float] = None):
        if entry is not None:
            self.redis.set(self.redis.KEY_PROGRESS_ENTRY, entry)

        if percent_add is not None:
            progress = self.redis.get(self.redis.KEY_PROGRESS)
            if progress is not None:
                self.redis.set(self.redis.KEY_PROGRESS, float(progress) + percent_add)

        self.redis.set(self.redis.KEY_LAST_UPDATE, int(time.time()))

    def set(self, entry: Optional[str] = None, percent: Optional[float] = None) -> None:
        if entry is not None:
            self.redis.set(self.redis.KEY_PROGRESS_ENTRY, entry)

        if percent is not None:
            self.redis.set(self.redis.KEY_PROGRESS, percent)

        self.redis.set(self.redis.KEY_LAST_UPDATE, int(time.time()))

    def retrieve(self) -> Tuple[Optional[str], Optional[str]]:
        return self.redis.get(self.redis.KEY_PROGRESS_ENTRY), self.redis.get(
            self.redis.KEY_PROGRESS
        )
