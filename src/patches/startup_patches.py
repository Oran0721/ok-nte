from ok.core.ui_config import resolve_ui_config
from ok.util.process import parse_arguments_to_map

from src.patches.i18n_patch import install_i18n_patch
from src.patches.task_group_filter_patch import install_task_group_filter_patch
from src.patches.theme_patch import install_theme_patch


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
    install_i18n_patch()
    _install_process_output_patch()
    _install_quiet_log_patch()
    if config.get("debug"):
        run_code_tab = ["src.ui.RunCodeTab", "RunCodeTab"]
        custom_tabs = config.setdefault("custom_tabs", [])
        if run_code_tab not in custom_tabs:
            custom_tabs.append(run_code_tab)

    if resolve_ui_config(config) is not None and not parse_arguments_to_map()["headless"]:
        install_task_group_filter_patch()
        install_theme_patch()
