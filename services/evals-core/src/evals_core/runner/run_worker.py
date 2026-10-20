"""一次评测运行的独立进程入口（2026-10-20，从 aichat-api 进程拆出）。

动因（用户实测）：评测全链（意图分类→检索→LLM→判分）CPU 重，在 API 进程内跑线程
会吃满 GIL，所有接口排队——跑任务时状态轮询 9KB 要 1.4s、切题集白屏。拆出后
API 进程空闲；进度/结果照旧经同一 SQLite（WAL）落库，前端查询接口不感知差异。

传参：--params 指向 suite_runner._spawn_worker 写的 JSON 文件，内容为
_run_suite_thread 的全量参数（题目清单、续跑 pre_done、rescore_map 等，均可
JSON 序列化），读回后 **params 直接执行；读完即删文件（API 侧重试删双保险）。

停止：「停止」按钮在 API 进程往 DB 落标志（result_store.request_stop），
本进程的监控线程轮询到后置 suite_runner 的本地事件——与旧 threading.Event
同语义：当前题跑完优雅退出，未完成题由 _finish_cancelled 收尾。

属主：启动即把 owner_pid 改写为本进程 pid，启动清扫据此区分
「worker 活着不要收」与「属主已死是僵尸」。"""
import argparse
import json
import logging
import os
import sys
import threading


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals_core.runner.run_worker")
    parser.add_argument("--params", required=True, help="_spawn_worker 写出的参数 JSON 文件路径")
    args = parser.parse_args(argv)

    try:
        with open(args.params, encoding="utf-8") as f:
            params = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"eval-worker 参数文件不可用: {exc}", file=sys.stderr)
        return 2
    try:
        os.unlink(args.params)
    except OSError:
        pass

    run_id = str(params.get("run_id") or "")
    if not run_id:
        print("eval-worker 参数缺少 run_id", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("evals.worker")
    logger.info("eval-worker 启动: run_id=%s pid=%s", run_id, os.getpid())

    from evals_core.runner import suite_runner
    from evals_core.storage import result_store

    result_store.init_db()
    # 评测器依赖注入与 API 进程启动同源（probe 检索函数 / intent 分类器）：
    # evals_runtime 在 services/aichat-api 目录，_spawn_worker 透传的 PYTHONPATH 可达。
    # 拿不到时 probe/intent 类题按既有「报错而非静默跳过」语义，普通题不受影响。
    try:
        import evals_runtime

        evals_runtime.configure_evaluators()
    except Exception as exc:  # noqa: BLE001
        logger.warning("worker 注入评测器依赖失败（probe/intent 题将报错而非静默跳过）: %s", exc)

    result_store.set_run_owner(run_id, os.getpid())

    stop_done = threading.Event()

    def _monitor() -> None:
        while not stop_done.wait(1.0):
            try:
                requested = result_store.is_stop_requested(run_id)
            except Exception:  # noqa: BLE001 轮询失败下一轮再来
                continue
            if requested and suite_runner.set_local_stop(run_id):
                logger.info("eval-worker 收到停止请求: run_id=%s", run_id)
                return

    monitor = threading.Thread(target=_monitor, daemon=True)
    monitor.start()
    try:
        # _run_suite_thread 自带异常保护（fail_run 落库）；这里只兜它之外的退出码
        suite_runner._run_suite_thread(**params)
    except Exception:  # noqa: BLE001
        logger.exception("eval-worker 执行异常退出: run_id=%s", run_id)
        return 1
    finally:
        stop_done.set()
    logger.info("eval-worker 收尾: run_id=%s", run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
