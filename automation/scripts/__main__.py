from __future__ import annotations

import importlib
import sys


COMMANDS = {
    "activity-state": "commands.activity_state",
    "board-service": "commands.board_service",
    "browser": "browser.browser_broker",
    "check-batch-plan": "commands.check_batch_plan",
    "check-campaign": "commands.check_campaign",
    "check-pool": "commands.check_pool",
    "cleanup": "commands.cleanup",
    "db-backup": "data.db_backup",
    "db-restore": "data.db_restore",
    "fetch-perf": "commands.fetch_perf",
    "judge-batch": "commands.judge_batch",
    "patrol": "commands.patrol",
    "review-queue": "commands.review_queue",
    "run-ads": "commands.run_ads",
    "run-audience": "commands.run_audience",
    "run-distribution": "commands.run_distribution",
    "run-distribution-ids": "commands.run_distribution_ids",
    "run-selection": "commands.run_selection",
    "run-taskgroup": "commands.run_taskgroup",
    "run-taskorder": "commands.run_taskorder",
    "visualize-perf": "commands.visualize_perf",
    "wait-login": "browser.wait_login",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("用法: python -m automation.scripts <command> [options]")
        print("命令: " + " ".join(sorted(COMMANDS)))
        return 0 if args else 2

    name = args.pop(0)
    module_name = COMMANDS.get(name)
    if not module_name:
        raise SystemExit("未知命令：%s\n可用命令：%s" % (name, " ".join(sorted(COMMANDS))))

    module = importlib.import_module("automation.scripts." + module_name)
    command = getattr(module, "main", None)
    if not callable(command):
        raise SystemExit("命令没有 main() 入口：%s" % name)

    sys.argv = ["python -m automation.scripts %s" % name, *args]
    result = command()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
