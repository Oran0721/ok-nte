from __future__ import annotations

import sys

from ok.core.ui_config import resolve_ui_config

_PATCH_INSTALLED = False


def resolve_runtime_ui_mode(config, argv=None) -> str | None:
    ui_config = resolve_ui_config(config)
    arguments = sys.argv[1:] if argv is None else argv
    if ui_config is None or any(argument in {"-h", "--headless"} for argument in arguments):
        return None
    return ui_config["type"]


def _install_pyappify_update_check_patch():
    import os

    import pyappify
    from ok.ui.qt.MainWindow import MainWindow

    original_schedule = MainWindow._schedule_update_check

    def _schedule_update_check_if_supported(self):
        if (
            "PYAPPIFY_PYTHON_TEST" not in os.environ
            and not pyappify._is_supported_pyappify_version(pyappify.pyappify_version)
        ):
            return
        return original_schedule(self)

    MainWindow._schedule_update_check = _schedule_update_check_if_supported


def _install_process_output_patch():
    import ok.util.process as ok_process

    original_build_cmd = ok_process._build_windows_start_command

    def _build_silent_windows_start_command(game_cmd: str, game_path: str, arguments=None):
        cmd = original_build_cmd(game_cmd, game_path, arguments)
        if ">nul" not in cmd.lower():
            cmd = f"{cmd} >nul 2>&1"
        return cmd

    ok_process._build_windows_start_command = _build_silent_windows_start_command


def _install_quiet_log_patch():
    """屏蔽启动配置转储和窗口轮询的 INFO 日志, 避免控制台刷屏; WARNING 及以上保留。"""
    import logging

    class _QuietLogFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if record.levelno >= logging.WARNING:
                return True
            if record.threadName == "update_window_size":
                return False
            message = record.getMessage()
            if message.startswith("do_init, config:"):
                return False
            return not message.startswith("hwnd_window:do_update_window_size")

    ok_logger = logging.getLogger("ok")
    if not any(isinstance(item, _QuietLogFilter) for item in ok_logger.filters):
        ok_logger.addFilter(_QuietLogFilter())


def install_startup_patches(config):
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    from src.ui.task_icons import Icon

    ui_mode = resolve_runtime_ui_mode(config)
    Icon.configure(ui_mode)

    from src.patches.i18n_patch import install_i18n_patch

    install_i18n_patch()
    _install_process_output_patch()
    _install_quiet_log_patch()
    if ui_mode == "qt":
        _install_pyappify_update_check_patch()
    # if ui_mode == "qt":
    #     from src.patches.task_tab_patch import install_task_tab_patch

    #     install_task_tab_patch()
    _PATCH_INSTALLED = True
