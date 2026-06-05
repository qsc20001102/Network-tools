import threading
from typing import Callable, Optional

from core.Function.common import popen_hidden, validate_host


OutputCallback = Callable[[str, Optional[str]], None]
DoneCallback = Callable[[], None]


class TracertFun:
    def __init__(self, output: OutputCallback, done: Optional[DoneCallback] = None):
        self.output = output
        self.done = done or (lambda: None)
        self.process = None
        self.stop_event = threading.Event()
        self.worker = None

    def start_tracert(self, target: str, max_hops: int = 20, timeout_ms: int = 800) -> None:
        target = validate_host(target)
        max_hops = max(1, min(int(max_hops), 64))
        timeout_ms = max(100, min(int(timeout_ms), 10000))

        if self.is_running():
            raise RuntimeError("路由追踪正在运行，请先停止当前任务")

        self.stop_event.clear()
        command = ["tracert", "-d", "-w", str(timeout_ms), "-h", str(max_hops), target]
        self.output(f"开始路由追踪: {target}，最大 {max_hops} 跳，超时 {timeout_ms}ms\n\n", "muted")
        self.worker = threading.Thread(target=self._run, args=(command,), daemon=True)
        self.worker.start()

    def _run(self, command) -> None:
        try:
            self.process = popen_hidden(command)
            if not self.process.stdout:
                return
            for line in self.process.stdout:
                if self.stop_event.is_set():
                    break
                self.output(line, None)
        except Exception as exc:
            self.output(f"\n路由追踪失败: {exc}\n", "error")
        finally:
            if self.process:
                try:
                    self.process.terminate()
                except Exception:
                    pass
                self.process = None
            if self.stop_event.is_set():
                self.output("\n路由追踪已停止\n", "warning")
            else:
                self.output("\n路由追踪完成\n", "success")
            self.done()

    def stop_tracert(self) -> None:
        if not self.is_running():
            raise RuntimeError("当前没有正在运行的路由追踪")
        self.stop_event.set()
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
        self.output("\n正在停止路由追踪...\n", "warning")

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())
