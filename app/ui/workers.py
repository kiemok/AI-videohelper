"""后台任务封装：用 QThreadPool 执行耗时任务，避免界面卡顿。

所有耗时的业务调用（数据导入、分析计算、大模型请求）都通过这里提交，
结果以 Qt 信号回到主线程更新界面。
"""

from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from app.core.logging_setup import get_logger

logger = get_logger(__name__)


class TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class FunctionTask(QRunnable):
    """把任意可调用对象包装成 QRunnable。"""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        # 交给 Python 掌控生命周期：线程池不自动删除，避免 QRunnable 包装对象失效
        # 后其 signals 属性被连带回收（详见 TaskRunner 的说明）。
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:  # pragma: no cover - 依赖 Qt 事件循环
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - 统一转为界面提示
            logger.error("后台任务失败: %s\n%s", exc, traceback.format_exc())
            self.signals.failed.emit(str(exc))
        else:
            self.signals.finished.emit(result)


class TaskRunner(QObject):
    """任务提交入口（由 AppContext 持有）。

    注意：``QThreadPool`` 会在 ``run()`` 返回后立刻删除 ``QRunnable``（autoDelete），
    而承载信号的 ``TaskSignals`` 是它的 Python 属性——若此时 Python 侧已无强引用，
    信号对象可能先于"投递到主线程的回调"被回收，导致 **回调偶发丢失**
    （表现为界面一直停在"处理中"）。因此这里在回调真正执行完之前，
    一直持有 task 的强引用（``_pending``），执行完毕后再释放。
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self._pending: set[FunctionTask] = set()

    def submit(
        self,
        fn: Callable[..., Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> FunctionTask:
        task = FunctionTask(fn, *args, **kwargs)
        self._pending.add(task)

        def finish(handler: Callable[[Any], None] | None, payload: Any) -> None:
            try:
                if handler is not None:
                    handler(payload)
            except Exception as exc:  # noqa: BLE001 - 回调异常不应打断界面
                logger.error("任务回调执行失败: %s\n%s", exc, traceback.format_exc())
            finally:
                self._pending.discard(task)

        task.signals.finished.connect(lambda result: finish(on_done, result))
        task.signals.failed.connect(lambda error: finish(on_error, error))
        self.pool.start(task)
        return task

    def wait(self, timeout_ms: int = 5000) -> bool:
        return self.pool.waitForDone(timeout_ms)
