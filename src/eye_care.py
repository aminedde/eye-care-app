# -*- coding: utf-8 -*-
"""
护眼卫士 v1.2 - 屏幕色温调节与护眼提醒
"""

import ctypes
import json
import math
import os
import socket
import sys
import threading
import time
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
    """屏幕Gamma控制器"""
    
    def __init__(self):
        self.supported = sys.platform == 'win32'
        if self.supported:
            self.gdi32 = ctypes.windll.gdi32
            self.user32 = ctypes.windll.user32

    def kelvin_to_rgb(self, kelvin):
        """
        色温转RGB - 使用 Tanner Helland 算法
        返回 (r, g, b)，范围 0.0 - 1.0
        """
        temp = kelvin / 100.0
        
        # 红色通道
        if temp <= 66:
            red = 255.0
        else:
            red = temp - 60
            red = 329.698727446 * math.pow(red, -0.1332047592)
            red = max(0, min(255, red))
        
        # 绿色通道
        if temp <= 66:
            green = 99.4708025861 * math.log(temp) - 161.1195681661
        else:
            green = temp - 60
            green = 288.1221695283 * math.pow(green, -0.0755148492)
        green = max(0, min(255, green))
        
        # 蓝色通道
        if temp >= 66:
            blue = 255.0
        elif temp <= 19:
            blue = 0.0
        else:
            blue = temp - 10
            blue = 138.5177312231 * math.log(blue) - 305.0447927307
            blue = max(0, min(255, blue))
        
        return red / 255.0, green / 255.0, blue / 255.0

    def set_gamma(self, temperature=6500, brightness=100, compensate=True):
        """设置屏幕Gamma"""
        if not self.supported:
            return False
        
        # 每次获取新的DC，避免失效
        hdc = self.user32.GetDC(None)
        if not hdc:
            return False
        
        try:
            # 获取色温RGB比例
            r, g, b = self.kelvin_to_rgb(temperature)
            
            # 亮度补偿
            if compensate and temperature < 6500:
                luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
                if luminance > 0.01:
                    factor = min(1.5, 1.0 / luminance)
                    r = min(1.0, r * factor)
                    g = min(1.0, g * factor)
                    b = min(1.0, b * factor)
            
            # 应用亮度
            bf = brightness / 100.0
            r *= bf
            g *= bf
            b *= bf
            
            # 创建Gamma Ramp
            ramp = (ctypes.c_ushort * 256 * 3)()
            for i in range(256):
                ramp[0][i] = min(65535, int(i * 256 * r))
                ramp[1][i] = min(65535, int(i * 256 * g))
                ramp[2][i] = min(65535, int(i * 256 * b))
            
            return bool(self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
        finally:
            self.user32.ReleaseDC(None, hdc)

    def restore(self):
        """恢复默认"""
        return self.set_gamma(6500, 100, False)


class EyeCareApp:
    """护眼软件主程序"""
    
    VERSION = "1.2.0"

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
        self.root.geometry("450x580")
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

        # 开关
        switch_frame = ttk.LabelFrame(main, text="护眼模式", padding="10")
        switch_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(switch_frame, text="启用护眼模式", variable=self.enabled_var,
                        command=self.toggle_eye_care).pack(anchor=tk.W)

        # 色温
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
        for text, temp in [("烛光", 1900), ("暖光", 2700), ("阅读", 3400), ("日光", 6500)]:
            ttk.Button(preset_frame, text=text, width=8, 
                      command=lambda t=temp: self.set_temp(t)).pack(side=tk.LEFT, padx=2, expand=True)

        # 亮度
        bright_frame = ttk.LabelFrame(main, text="亮度调节", padding="10")
        bright_frame.pack(fill=tk.X, pady=(0, 10))
        
        bright_header = ttk.Frame(bright_frame)
        bright_header.pack(fill=tk.X)
        ttk.Label(bright_header, text="亮度:").pack(side=tk.LEFT)
        self.bright_label = ttk.Label(bright_header, text=f"{self.brightness_var.get()}%", style="Value.TLabel")
        self.bright_label.pack(side=tk.RIGHT)
        
        ttk.Scale(bright_frame, from_=20, to=100, variable=self.brightness_var,
                  command=self.on_bright_change).pack(fill=tk.X, pady=5)
        
        ttk.Checkbutton(bright_frame, text="亮度补偿（降低色温时保持亮度）",
                        variable=self.compensate_var, command=self.on_setting_change).pack(anchor=tk.W)

        # 休息提醒
        remind_frame = ttk.LabelFrame(main, text="休息提醒", padding="10")
        remind_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Checkbutton(remind_frame, text="启用定时休息提醒", variable=self.reminder_var,
                        command=self.save_config).pack(anchor=tk.W)
        
        interval_row = ttk.Frame(remind_frame)
        interval_row.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(interval_row, text="间隔:").pack(side=tk.LEFT)
        ttk.Spinbox(interval_row, from_=15, to=120, width=5, textvariable=self.interval_var,
                    command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Label(interval_row, text="分钟").pack(side=tk.LEFT)
        
        self.remind_label = ttk.Label(remind_frame, text="", foreground="gray")
        self.remind_label.pack(anchor=tk.W, pady=(5, 0))

        # 其他
        other_frame = ttk.LabelFrame(main, text="其他", padding="10")
        other_frame.pack(fill=tk.X, pady=(0, 10))
        
        tray_state = "normal" if TRAY_AVAILABLE else "disabled"
        ttk.Checkbutton(other_frame, text="关闭时最小化到托盘",
                        variable=self.minimize_var, command=self.save_config,
                        state=tray_state).pack(anchor=tk.W)

        # 按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_frame, text="恢复默认", command=self.reset).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="关于", command=self.about).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="退出", command=self.quit_app).pack(side=tk.RIGHT)

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

    def on_setting_change(self):
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
            m, s = divmod(int(left), 60)
            self.remind_label.config(text=f"下次提醒: {m:02d}:{s:02d}")

    def show_reminder(self):
        def show():
            win = tk.Toplevel(self.root)
            win.title("休息提醒")
            win.geometry("380x200")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            win.update_idletasks()
            x = (win.winfo_screenwidth() - 380) // 2
            y = (win.winfo_screenheight() - 200) // 2
            win.geometry(f"+{x}+{y}")
            
            f = ttk.Frame(win, padding="25")
            f.pack(fill=tk.BOTH, expand=True)
            ttk.Label(f, text="休息一下", font=("Microsoft YaHei UI", 16, "bold")).pack(pady=(0, 10))
            ttk.Label(f, text="您已连续使用电脑较长时间", font=("Microsoft YaHei UI", 10)).pack()
            ttk.Label(f, text="建议看看远处，活动一下", font=("Microsoft YaHei UI", 10)).pack(pady=5)
            ttk.Button(f, text="知道了", command=win.destroy, width=10).pack(pady=10)
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
            d.ellipse([12, 22, 52, 42], fill='white')
            d.ellipse([27, 27, 37, 37], fill='#1a1a1a')
            return img
        
        menu = pystray.Menu(
            pystray.MenuItem("显示", lambda: self.root.after(0, self.show_window), default=True),
            pystray.MenuItem("护眼", lambda: self.root.after(0, self.tray_toggle),
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
        self.gamma.restore()
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
        messagebox.showinfo("关于", f"""护眼卫士 v{self.VERSION}

功能特性:
• 色温调节 1900K-6500K
• 亮度调节 20%-100%
• 自动亮度补偿
• 定时休息提醒
• 系统托盘运行

色温建议:
• 白天办公: 5500-6500K
• 傍晚使用: 4000-5000K
• 夜间阅读: 2700-3400K
• 深夜模式: 1900-2700K""")

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config.update(json.load(f))
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
        y = (self.root.winfo_screenheight() - 580) // 2
        self.root.geometry(f"+{x}+{y}")
        self.root.mainloop()


def main():
    try:
        global _lock
        _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock.bind(('127.0.0.1', 52846))
    except:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("提示", "护眼卫士已在运行")
        sys.exit(0)
    
    EyeCareApp().run()


if __name__ == "__main__":
    main()
