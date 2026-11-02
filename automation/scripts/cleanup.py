# -*- coding: utf-8 -*-
"""清理项目日志、临时文件和浏览器可重建缓存。"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import runtime_state


REPO = Path(__file__).resolve().parents[2]
LOG_DAYS = 7
TEMP_DAYS = 1
SCREENSHOT_DAYS = 30
BROWSER_CHECK_DAYS = 7
CACHE_TRIGGER_BYTES = 200 * 1024 * 1024
PROFILE_CONFIRM_BYTES = 1024 * 1024 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
CLEANUP_STATE = REPO / ".local" / "browser-cleanup.json"

CACHE_PATHS = (
    "Default/Cache",
    "Default/Code Cache",
    "Default/GPUCache",
    "Default/DawnGraphiteCache",
    "Default/DawnWebGPUCache",
    "BrowserMetrics",
    "Crashpad",
    "GPUPersistentCache",
    "GrShaderCache",
    "ShaderCache",
    "component_crx_cache",
    "extensions_crx_cache",
)
DEEP_CACHE_PATHS = (
    "Default/EdgeCoupons",
    "Default/JumpListIconsRecentClosed",
    "Default/JumpListIconsRecentWorkspacesV2",
    "Default/JumpListIconsTopSites",
    "Edge Entity Extraction",
    "EdgeLanguageDetectionModel",
    "ProvenanceData",
    "ProvenanceDataAllowList",
    "ProvenanceDataTensors",
    "Safe Browsing",
    "Subresource Filter",
    "Typosquatting",
)


def _now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def _iter_files(root: Path):
    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            yield path


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _old_files(paths, cutoff: float) -> list[Path]:
    return [
        path for path in paths
        if path.exists() and path.stat().st_mtime < cutoff
    ]


def _collect_logs(repo: Path, extra_logs: list[Path]) -> list[Path]:
    paths = []
    for log_dir in (repo / "activities").glob("*/日志"):
        paths.extend(log_dir.rglob("*.log"))
    tmp = repo / "automation" / "_tmp"
    paths.extend(tmp.rglob("*.log"))
    paths.extend((repo / "web").rglob("*.log"))
    paths.extend(extra_logs)
    return [path for path in paths if path.is_file() and not path.is_symlink()]


def _collect_screenshots(repo: Path) -> list[Path]:
    paths = []
    for log_dir in (repo / "activities").glob("*/日志"):
        paths.extend(
            path for path in log_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
    tmp = repo / "automation" / "_tmp"
    paths.extend(
        path for path in tmp.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    return [path for path in paths if not path.is_symlink()]


def _prune_empty_dirs(root: Path) -> None:
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def cleanup_project_files(
    repo: Path | str = REPO,
    now: datetime.datetime | None = None,
    dry_run: bool = False,
    extra_logs: list[Path] | None = None,
) -> dict:
    repo = Path(repo).resolve()
    now = now or _now()
    logs = _old_files(_collect_logs(repo, extra_logs or []), (now - datetime.timedelta(days=LOG_DAYS)).timestamp())
    screenshots = _old_files(
        _collect_screenshots(repo),
        (now - datetime.timedelta(days=SCREENSHOT_DAYS)).timestamp(),
    )
    tmp = repo / "automation" / "_tmp"
    temp_files = [
        path for path in _iter_files(tmp)
        if path.suffix.lower() != ".log"
        and path.suffix.lower() not in IMAGE_SUFFIXES
        and path.stat().st_mtime < (now - datetime.timedelta(days=TEMP_DAYS)).timestamp()
    ]

    groups = {"logs": logs, "screenshots": screenshots, "temp": temp_files}
    if not dry_run:
        for paths in groups.values():
            for path in paths:
                path.unlink()
        _prune_empty_dirs(tmp)
    return {
        "dry_run": dry_run,
        "removed": {name: [str(path) for path in paths] for name, paths in groups.items()},
    }


def browser_cache_size(profile: Path | str) -> int:
    profile = Path(profile)
    total = 0
    for relative in CACHE_PATHS:
        path = profile / relative
        if not path.exists():
            continue
        if path.is_file():
            total += path.stat().st_size
        else:
            total += sum(
                item.stat().st_size for item in path.rglob("*")
                if item.is_file() and not item.is_symlink()
            )
    return total


def profile_size(profile: Path | str) -> int:
    profile = Path(profile)
    if not profile.is_dir():
        return 0
    return sum(
        path.stat().st_size for path in profile.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def browser_is_running(profile: Path | str) -> bool:
    state = runtime_state.read_state("browser")
    try:
        pid = int(state.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    return bool(pid and runtime_state.process_matches(pid, [str(profile)]))


def clean_browser_cache(
    profile: Path | str,
    dry_run: bool = False,
    deep: bool = False,
) -> dict:
    profile = Path(profile).resolve()
    removed = []
    cache_paths = CACHE_PATHS + (DEEP_CACHE_PATHS if deep else ())
    for relative in cache_paths:
        path = (profile / relative).resolve()
        if os.path.commonpath([str(profile), str(path)]) != str(profile):
            raise RuntimeError(f"缓存路径越界：{path}")
        if not path.exists():
            continue
        removed.append(str(path))
        if not dry_run:
            _remove_path(path)
    return {"dry_run": dry_run, "removed": removed}


def _read_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _parse_time(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def maybe_clean_browser_profile(
    profile: Path | str,
    state_path: Path | str = CLEANUP_STATE,
    now: datetime.datetime | None = None,
    profile_limit: int = PROFILE_CONFIRM_BYTES,
) -> dict:
    """浏览器停止后最多每 7 天检查一次；大 profile 等待人工确认。"""
    profile = Path(profile).resolve()
    state_path = Path(state_path)
    now = now or _now()
    state = _read_state(state_path)
    last_check = _parse_time(state.get("last_check"))
    if last_check and now - last_check < datetime.timedelta(days=BROWSER_CHECK_DAYS):
        return {"status": "skipped", "reason": "距离上次检查不足 7 天"}

    cache_before = browser_cache_size(profile)
    total_before = profile_size(profile)
    state.update({
        "last_check": now.isoformat(timespec="seconds"),
        "cache_bytes_before": cache_before,
        "profile_bytes": total_before,
    })
    if total_before > profile_limit:
        state["status"] = "needs_confirmation"
        _write_state(state_path, state)
        return {
            "status": "needs_confirmation",
            "profile_bytes": total_before,
            "cache_bytes": cache_before,
        }

    last_clean = _parse_time(state.get("last_clean"))
    clean_is_stale = (
        last_clean is None
        or now - last_clean >= datetime.timedelta(days=BROWSER_CHECK_DAYS)
    )
    if cache_before < CACHE_TRIGGER_BYTES and not clean_is_stale:
        state["status"] = "skipped"
        _write_state(state_path, state)
        return {
            "status": "skipped",
            "reason": "缓存未超过 200 MB，且 7 天内已清理",
            "profile_bytes": total_before,
            "cache_bytes": cache_before,
        }

    clean_browser_cache(profile)
    state.update({
        "last_clean": now.isoformat(timespec="seconds"),
        "cache_bytes_after": browser_cache_size(profile),
        "status": "cleaned",
    })
    _write_state(state_path, state)
    return {
        "status": "cleaned",
        "profile_bytes": total_before,
        "cache_bytes_before": cache_before,
        "cache_bytes_after": state["cache_bytes_after"],
    }


def clean_browser_profile(
    profile: Path | str,
    state_path: Path | str = CLEANUP_STATE,
    now: datetime.datetime | None = None,
    deep: bool = False,
    dry_run: bool = False,
    profile_limit: int = PROFILE_CONFIRM_BYTES,
) -> dict:
    profile = Path(profile).resolve()
    now = now or _now()
    if not dry_run and browser_is_running(profile):
        raise RuntimeError("公共浏览器仍在运行，请先停止后再清理 profile 缓存")
    total = profile_size(profile)
    if total > profile_limit and not deep:
        return {
            "status": "needs_confirmation",
            "profile_bytes": total,
            "cache_bytes": browser_cache_size(profile),
        }
    cache_before = browser_cache_size(profile)
    result = clean_browser_cache(profile, dry_run=dry_run, deep=deep)
    if not dry_run:
        state = _read_state(Path(state_path))
        state.update({
            "last_check": now.isoformat(timespec="seconds"),
            "last_clean": now.isoformat(timespec="seconds"),
            "profile_bytes": total,
            "cache_bytes_before": cache_before,
            "cache_bytes_after": browser_cache_size(profile),
            "status": "cleaned",
        })
        _write_state(Path(state_path), state)
    return {
        "status": "dry_run" if dry_run else "cleaned",
        "profile_bytes": total,
        "cache_bytes_before": cache_before,
        "cache_bytes_after": browser_cache_size(profile),
        "removed": result["removed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="清理日志、临时文件和浏览器缓存")
    parser.add_argument("--repo", default=str(REPO), help="项目根目录")
    parser.add_argument("--browser-profile", action="store_true", help="同时清理浏览器缓存")
    parser.add_argument("--deep", action="store_true", help="确认 profile 超过 1 GB 时仍清理")
    parser.add_argument("--dry-run", action="store_true", help="只列出会删除的文件")
    args = parser.parse_args()

    try:
        repo = Path(args.repo).resolve()
        extra_logs = [Path(tempfile.gettempdir()) / "board_service.log"]
        result = cleanup_project_files(repo, dry_run=args.dry_run, extra_logs=extra_logs)
        for name, paths in result["removed"].items():
            print(f"{name}: {len(paths)} 个")
            for path in paths:
                print(f"  {'WOULD REMOVE' if args.dry_run else 'REMOVED'} {path}")

        if args.browser_profile:
            browser = clean_browser_profile(
                repo / ".browser-profile",
                state_path=repo / ".local" / "browser-cleanup.json",
                deep=args.deep,
                dry_run=args.dry_run,
            )
            if browser["status"] == "needs_confirmation":
                print(
                    f"BROWSER CACHE: NEEDS CONFIRMATION | profile={browser['profile_bytes']} bytes "
                    f"cache={browser['cache_bytes']} bytes；确认后加 --deep"
                )
                return 2
            print(
                f"BROWSER CACHE: {'DRY RUN' if args.dry_run else 'OK'} | "
                f"cache {browser['cache_bytes_before']} -> {browser['cache_bytes_after']} bytes"
            )
    except Exception as exc:
        print(f"CLEANUP: FAILED | {str(exc).splitlines()[0][:240]}")
        return 1

    print("CLEANUP: OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
