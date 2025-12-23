# -*- coding: utf-8 -*-
"""
护眼卫士 v1.1 - 屏幕色温调节与护眼提醒
"""

import ctypes
import json
import os
import sys
import threading
import time
import socket
import tkinter as tk
from tkinter import ttk, messagebox

if getattr(sys, 'frozen', False):
    APP_PATH = os.path.dirname(sys.executable)
else:
    APP_PATH = os.path.dirname(os.path.abspath(__file__))

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False


class GammaController:
    def __init__(self):
        if sys.platform != 'win32':
            self.supported = False
            return
        self.supported = True
        self.gdi32 = ctypes.windll.gdi32
        self.user32 = ctypes.windll.user32
        self.hdc = self.user32.GetDC(None)

    def kelvin_to_rgb(self, kelvin):
        temp = kelvin / 100.0
        if temp <= 66:
            red = 255
        else:
            red = temp - 60
            red = 329.698727446 * (red ** -0.1332047592)
            red = max(0, min(255, red))
        if temp <= 66:
            green = temp
            if temp > 1:
                green = 99.4708025861 * (green ** 0.1) - 161.1195681661
            else:
                green = 0
        else:
            green = temp - 60
            green = 288.1221695283 * (green ** -0.0755148492)
        green = max(0, min(255, green))
        if temp >= 66:
            blue = 255
        elif temp <= 19:
            blue = 0
        else:
            blue = temp - 10
            if blue > 0:
                blue = 138.5177312231 * (blue ** 0.1) - 305.0447927307
            else:
                blue = 0
        blue = max(0, min(255, blue))
        return red / 255.0, green / 255.0, blue / 255.0

    def set_gamma(self, temperature=6500, brightness=100, compensate=True):
        if not self.supported:
            return False
        r, g, b = self.kelvin_to_rgb(temperature)
        if compensate and temperature < 6500:
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if lum > 0:
                comp = min(1.4, 1.0 / lum)
                r = min(1.0, r * comp)
                g = min(1.0, g * comp)
                b = min(1.0, b * comp)
        bf = brightness / 100.0
        ramp = (ctypes.c_ushort * 256 * 3)()
        for i in range(256):
            base = int(i * 256 * bf)
            ramp[0][i] = min(65535, max(0, int(base * r)))
            ramp[1][i] = min(65535, max(0, int(base * g)))
            ramp[2][i] = min(65535, max(0, int(base * b)))
        return self.gdi32.SetDeviceGammaRamp(self.hdc, ctypes.byref(ramp)) != 0

    def restore(self):
        return self.set_gamma(6500, 100, False)

    def cleanup(self):
        if self.supported:
            self.restore()
            if self.hdc:
                self.user32.ReleaseDC(None, self.hdc)


class EyeCareApp:
    VERSION = "1.1.0"

    def __init__(self):
        self.config_file = os.path.join(APP_PATH, "eye_care_config.json")
        self.gamma = GammaController()
        self.running = True
        self.tray_icon = None
        self.last_reminder = time.time()
        self.config = {
            "enabled": True,
            "temperature": 5000,
            "brightness": 100,
            "compensate": True,
            "reminder_enabled": True,
            "reminder_interval": 45,
            "minimize_to_tray": True,
        }
        self.load_config()
        self.create_window()
        if self.config["enabled"]:
            self.apply_settings()
        self.start_reminder_thread()
        if TRAY_AVAILABLE:
            self.create_tray_icon()

    def create_window(self):
        self.root = tk.Tk()
        self.root.title(f"护眼卫士 v{self.VERSION}")
        self.root.geometry("450x620")
        self.root.resizable(False, False)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass
        self.enabled_var = tk.BooleanVar(value=self.config["enabled"])
        self.temp_var = tk.IntVar(value=self.config["temperature"])
        self.brightness_var = tk.IntVar(value=self.config["brightness"])
        self.compensate_var = tk.BooleanVar(value=self.config.get("compensate", True))
        self.reminder_var = tk.BooleanVar(value=self.config["reminder_enabled"])
        self.interval_var = tk.IntVar(value=self.config["reminder_interval"])
        self.minimize_var = tk.BooleanVar(value=self.config["minimize_to_tray"])
        self.create_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_ui(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Value.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Info.TLabel", font=("Microsoft YaHei UI", 9), foreground="#666")
        main = ttk.Frame(self.root, padding="20")
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="护眼卫士", style="Title.TLabel").pack(pady=(0, 15))

        switch_frame = ttk.LabelFrame(main, text="护眼模式", padding="10")
        switch_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(switch_frame, text="启用护眼模式", variable=self.enabled_var,
                        command=self.toggle_eye_care).pack(anchor=tk.W)

        temp_frame = ttk.LabelFrame(main, text="色温调节", padding="10")
        temp_frame.pack(fill=tk.X, pady=(0, 10))
        temp_header = ttk.Frame(temp_frame)
        temp_header.pack(fill=tk.X)
        ttk.Label(temp_header, text="色温:").pack(side=tk.LEFT)
        self.temp_label = ttk.Label(temp_header, text=f"{self.temp_var.get()}K", style="Value.TLabel")
        self.temp_label.pack(side=tk.RIGHT)
        self.temp_scale = ttk.Scale(temp_frame, from_=1900, to=6500, variable=self.temp_var,
                                    command=self.on_temp_change)
        self.temp_scale.pack(fill=tk.X, pady=5)
        hint_frame = ttk.Frame(temp_frame)
        hint_frame.pack(fill=tk.X)
        ttk.Label(hint_frame, text="暖 1900K", foreground="#FF5722", font=("", 8)).pack(side=tk.LEFT)
        ttk.Label(hint_frame, text="冷 6500K", foreground="#03A9F4", font=("", 8)).pack(side=tk.RIGHT)
        preset_frame = ttk.Frame(temp_frame)
        preset_frame.pack(fill=tk.X, pady=(8, 0))
        presets = [("烛光", 1900), ("壁炉", 2400), ("暖灯", 3400), ("日光", 6500)]
        for text, temp in presets:
            btn = ttk.Button(preset_frame, text=text, width=8, command=lambda t=temp: self.set_temp(t))
            btn.pack(side=tk.LEFT, padx=2, expand=True)

        bright_frame = ttk.LabelFrame(main, text="亮度调节", padding="10")
        bright_frame.pack(fill=tk.X, pady=(0, 10))
        bright_header = ttk.Frame(bright_frame)
        bright_header.pack(fill=tk.X)
        ttk.Label(bright_header, text="亮度:").pack(side=tk.LEFT)
        self.bright_label = ttk.Label(bright_header, text=f"{self.brightness_var.get()}%", style="Value.TLabel")
        self.bright_label.pack(side=tk.RIGHT)
        ttk.Scale(bright_frame, from_=20, to=100, variable=self.brightness_var,
                  command=self.on_bright_change).pack(fill=tk.X, pady=5)
        ttk.Checkbutton(bright_frame, text="自动亮度补偿（防止变暗）",
                        variable=self.compensate_var, command=self.on_compensate_change).pack(anchor=tk.W)

        remind_frame = ttk.LabelFrame(main, text="休息提醒", padding="10")
        remind_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(remind_frame, text="启用定时休息提醒", variable=self.reminder_var,
                        command=self.save_config).pack(anchor=tk.W)
        interval_row = ttk.Frame(remind_frame)
        interval_row.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(interval_row, text="提醒间隔:").pack(side=tk.LEFT)
        ttk.Spinbox(interval_row, from_=15, to=120, width=6, textvariable=self.interval_var,
                    command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Label(interval_row, text="分钟").pack(side=tk.LEFT)
        self.remind_label = ttk.Label(remind_frame, text="", foreground="gray")
        self.remind_label.pack(anchor=tk.W, pady=(5, 0))

        other_frame = ttk.LabelFrame(main, text="其他设置", padding="10")
        other_frame.pack(fill=tk.X, pady=(0, 10))
        tray_state = "normal" if TRAY_AVAILABLE else "disabled"
        ttk.Checkbutton(other_frame, text="关闭窗口时最小化到托盘",
                        variable=self.minimize_var, command=self.save_config,
                        state=tray_state).pack(anchor=tk.W)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_frame, text="恢复默认", command=self.reset).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="关于", command=self.about).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="退出程序", command=self.quit_app).pack(side=tk.RIGHT)

    def toggle_eye_care(self):
        self.config["enabled"] = self.enabled_var.get()
        if self.config["enabled"]:
            self.apply_settings()
        else:
            self.gamma.restore()
        self.save_config()

    def on_temp_change(self, val):
        temp = int(float(val))
        self.temp_var.set(temp)
        self.temp_label.config(text=f"{temp}K")
        self.config["temperature"] = temp
        if self.enabled_var.get():
            self.apply_settings()
        self.save_config()

    def set_temp(self, temp):
        self.temp_var.set(temp)
        self.temp_label.config(text=f"{temp}K")
        self.config["temperature"] = temp
        if not self.enabled_var.get():
            self.enabled_var.set(True)
            self.config["enabled"] = True
        self.apply_settings()
        self.save_config()

    def on_bright_change(self, val):
        bright = int(float(val))
        self.brightness_var.set(bright)
        self.bright_label.config(text=f"{bright}%")
        self.config["brightness"] = bright
        if self.enabled_var.get():
            self.apply_settings()
        self.save_config()

    def on_compensate_change(self):
        self.config["compensate"] = self.compensate_var.get()
        if self.enabled_var.get():
            self.apply_settings()
        self.save_config()

    def apply_settings(self):
        self.gamma.set_gamma(
            temperature=self.config["temperature"],
            brightness=self.config["brightness"],
            compensate=self.config.get("compensate", True)
        )

    def reset(self):
        self.temp_var.set(6500)
        self.brightness_var.set(100)
        self.enabled_var.set(False)
        self.compensate_var.set(True)
        self.config.update({
            "temperature": 6500,
            "brightness": 100,
            "enabled": False,
            "compensate": True
        })
        self.temp_label.config(text="6500K")
        self.bright_label.config(text="100%")
        self.gamma.restore()
        self.save_config()

    def start_reminder_thread(self):
        def loop():
            while self.running:
                if self.config["reminder_enabled"]:
                    interval = self.config["reminder_interval"] * 60
                    if time.time() - self.last_reminder >= interval:
                        self.show_reminder()
                        self.last_reminder = time.time()
                try:
                    self.root.after(0, self.update_remind_label)
                except:
                    pass
                time.sleep(1)
        threading.Thread(target=loop, daemon=True).start()

    def update_remind_label(self):
        if not self.config["reminder_enabled"]:
            self.remind_label.config(text="提醒已关闭")
            return
        left = self.config["reminder_interval"] * 60 - (time.time() - self.last_reminder)
        if left > 0:
            mins = int(left // 60)
            secs = int(left % 60)
            self.remind_label.config(text=f"距离下次提醒: {mins:02d}:{secs:02d}")

    def show_reminder(self):
        def show():
            win = tk.Toplevel(self.root)
            win.title("休息提醒")
            win.geometry("400x220")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            win.update_idletasks()
            x = (win.winfo_screenwidth() - 400) // 2
            y = (win.winfo_screenheight() - 220) // 2
            win.geometry(f"+{x}+{y}")
            f = ttk.Frame(win, padding="25")
            f.pack(fill=tk.BOTH, expand=True)
            ttk.Label(f, text="休息一下", font=("Microsoft YaHei UI", 18, "bold")).pack(pady=(0, 10))
            ttk.Label(f, text="您已连续使用电脑较长时间", font=("Microsoft YaHei UI", 11)).pack()
            ttk.Label(f, text="建议看看远处，闭眼休息片刻", font=("Microsoft YaHei UI", 11)).pack(pady=5)
            ttk.Button(f, text="我知道了", command=win.destroy, width=12).pack(pady=15)
            win.after(60000, lambda: win.destroy() if win.winfo_exists() else None)
        try:
            self.root.after(0, show)
        except:
            pass

    def create_tray_icon(self):
        def make_icon():
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse([4, 4, 60, 60], fill='#4CAF50', outline='#2E7D32', width=2)
            d.ellipse([12, 22, 52, 42], fill='white', outline='#333', width=1)
            d.ellipse([26, 27, 38, 37], fill='#1a1a1a')
            d.ellipse([29, 29, 35, 35], fill='white')
            return img
        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", lambda: self.root.after(0, self.show_window), default=True),
            pystray.MenuItem("护眼模式", lambda: self.root.after(0, self.tray_toggle),
                             checked=lambda _: self.config["enabled"]),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self.root.after(0, self.quit_app))
        )
        self.tray_icon = pystray.Icon("EyeCare", make_icon(), "护眼卫士", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def tray_toggle(self):
        self.enabled_var.set(not self.enabled_var.get())
        self.toggle_eye_care()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_closing(self):
        if self.minimize_var.get() and TRAY_AVAILABLE:
            self.root.withdraw()
        else:
            self.quit_app()

    def quit_app(self):
        self.running = False
        self.gamma.cleanup()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except:
                pass
        self.save_config()
        self.root.quit()
        self.root.destroy()
        sys.exit(0)

    def about(self):
        msg = f"""护眼卫士 v{self.VERSION}

功能:
- 色温调节 1900K - 6500K
- 亮度调节 20% - 100%
- 自动亮度补偿
- 定时休息提醒
- 系统托盘运行

色温建议:
- 白天: 5500K - 6500K
- 傍晚: 4000K - 5000K
- 夜间: 2400K - 3400K
- 深夜: 1900K - 2400K"""
        messagebox.showinfo("关于", msg)

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.config.update(loaded)
        except:
            pass

    def save_config(self):
        try:
            self.config["reminder_enabled"] = self.reminder_var.get()
            self.config["minimize_to_tray"] = self.minimize_var.get()
            self.config["reminder_interval"] = self.interval_var.get()
            self.config["compensate"] = self.compensate_var.get()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except:
            pass

    def run(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 450) // 2
        y = (self.root.winfo_screenheight() - 620) // 2
        self.root.geometry(f"+{x}+{y}")
        self.root.mainloop()


def main():
    try:
        global _lock_socket
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.bind(('127.0.0.1', 52846))
    except:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("提示", "护眼卫士已在运行")
        sys.exit(0)
    EyeCareApp().run()


if __name__ == "__main__":
    main()
