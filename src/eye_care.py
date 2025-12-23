# -*- coding: utf-8 -*-
"""
护眼卫士 v1.0 - PC端屏幕护眼软件
GitHub Actions 自动打包版本
"""

import ctypes
import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

# 获取程序运行目录
if getattr(sys, 'frozen', False):
    APP_PATH = os.path.dirname(sys.executable)
else:
    APP_PATH = os.path.dirname(os.path.abspath(__file__))

# 尝试导入托盘库
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False


class GammaController:
    """屏幕Gamma控制器"""
    
    def __init__(self):
        # 仅Windows支持
        if sys.platform != 'win32':
            self.supported = False
            return
        
        self.supported = True
        self.gdi32 = ctypes.windll.gdi32
        self.user32 = ctypes.windll.user32
        self.hdc = self.user32.GetDC(None)
        
        self.temperature_presets = {
            6500: (1.0, 1.0, 1.0),
            6000: (1.0, 0.96, 0.90),
            5500: (1.0, 0.93, 0.82),
            5000: (1.0, 0.89, 0.74),
            4500: (1.0, 0.85, 0.66),
            4000: (1.0, 0.80, 0.58),
            3500: (1.0, 0.75, 0.50),
            3000: (1.0, 0.68, 0.42),
            2700: (1.0, 0.62, 0.35),
            2400: (1.0, 0.55, 0.28),
        }
    
    def _kelvin_to_rgb(self, kelvin):
        temps = sorted(self.temperature_presets.keys())
        if kelvin >= max(temps):
            return self.temperature_presets[max(temps)]
        if kelvin <= min(temps):
            return self.temperature_presets[min(temps)]
        
        for i in range(len(temps) - 1):
            if temps[i] <= kelvin <= temps[i + 1]:
                t = (kelvin - temps[i]) / (temps[i + 1] - temps[i])
                rgb1 = self.temperature_presets[temps[i]]
                rgb2 = self.temperature_presets[temps[i + 1]]
                return tuple(rgb1[j] + t * (rgb2[j] - rgb1[j]) for j in range(3))
        return (1.0, 1.0, 1.0)
    
    def set_gamma(self, temperature=6500, brightness=100):
        if not self.supported:
            return False
        
        r_ratio, g_ratio, b_ratio = self._kelvin_to_rgb(temperature)
        brightness_factor = brightness / 100.0
        ramp = (ctypes.c_ushort * 256 * 3)()
        
        for i in range(256):
            base = int(i * 256 * brightness_factor)
            ramp[0][i] = min(65535, int(base * r_ratio))
            ramp[1][i] = min(65535, int(base * g_ratio))
            ramp[2][i] = min(65535, int(base * b_ratio))
        
        return self.gdi32.SetDeviceGammaRamp(self.hdc, ctypes.byref(ramp)) != 0
    
    def restore_default(self):
        return self.set_gamma(6500, 100)
    
    def cleanup(self):
        if self.supported:
            self.restore_default()
            if self.hdc:
                self.user32.ReleaseDC(None, self.hdc)


class EyeCareApp:
    """护眼软件主程序"""
    
    VERSION = "1.0.0"
    
    def __init__(self):
        self.config_file = os.path.join(APP_PATH, "eye_care_config.json")
        self.gamma = GammaController()
        self.running = True
        self.tray_icon = None
        self.last_reminder = time.time()
        
        self.config = {
            "enabled": True,
            "temperature": 5000,
            "brightness": 90,
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
        self.root.geometry("430x580")
        self.root.resizable(False, False)
        
        # 设置DPI感知
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass
        
        self.enabled_var = tk.BooleanVar(value=self.config["enabled"])
        self.temp_var = tk.IntVar(value=self.config["temperature"])
        self.brightness_var = tk.IntVar(value=self.config["brightness"])
        self.reminder_var = tk.BooleanVar(value=self.config["reminder_enabled"])
        self.interval_var = tk.IntVar(value=self.config["reminder_interval"])
        self.minimize_var = tk.BooleanVar(value=self.config["minimize_to_tray"])
        
        self.create_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_ui(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Value.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Subtitle.TLabel", font=("Microsoft YaHei UI", 9), foreground="gray")
        
        main = ttk.Frame(self.root, padding="20")
        main.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        ttk.Label(main, text="🛡️ 护眼卫士", style="Title.TLabel").pack(pady=(0, 5))
        ttk.Label(main, text="保护眼睛，从现在开始", style="Subtitle.TLabel").pack(pady=(0, 15))
        
        # 开关
        switch_frame = ttk.LabelFrame(main, text="护眼模式", padding="12")
        switch_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Checkbutton(switch_frame, text="启用护眼模式", variable=self.enabled_var,
                       command=self.toggle_eye_care).pack(anchor=tk.W)
        
        # 色温
        temp_frame = ttk.LabelFrame(main, text="色温调节", padding="12")
        temp_frame.pack(fill=tk.X, pady=(0, 12))
        
        temp_header = ttk.Frame(temp_frame)
        temp_header.pack(fill=tk.X)
        ttk.Label(temp_header, text="色温:").pack(side=tk.LEFT)
        self.temp_label = ttk.Label(temp_header, text=f"{self.temp_var.get()}K", style="Value.TLabel")
        self.temp_label.pack(side=tk.RIGHT)
        
        ttk.Scale(temp_frame, from_=2400, to=6500, variable=self.temp_var,
                 command=self.on_temp_change).pack(fill=tk.X, pady=5)
        
        hint_frame = ttk.Frame(temp_frame)
        hint_frame.pack(fill=tk.X)
        ttk.Label(hint_frame, text="🔥 暖", foreground="#FF9800").pack(side=tk.LEFT)
        ttk.Label(hint_frame, text="❄️ 冷", foreground="#03A9F4").pack(side=tk.RIGHT)
        
        preset_frame = ttk.Frame(temp_frame)
        preset_frame.pack(fill=tk.X, pady=(10, 0))
        for text, temp in [("🌅 日落", 4000), ("💡 暖光", 3500), ("🕯️ 烛光", 2700), ("☀️ 日光", 6500)]:
            ttk.Button(preset_frame, text=text, width=9,
                      command=lambda t=temp: self.set_temp(t)).pack(side=tk.LEFT, padx=2, expand=True)
        
        # 亮度
        bright_frame = ttk.LabelFrame(main, text="亮度调节", padding="12")
        bright_frame.pack(fill=tk.X, pady=(0, 12))
        
        bright_header = ttk.Frame(bright_frame)
        bright_header.pack(fill=tk.X)
        ttk.Label(bright_header, text="亮度:").pack(side=tk.LEFT)
        self.bright_label = ttk.Label(bright_header, text=f"{self.brightness_var.get()}%", style="Value.TLabel")
        self.bright_label.pack(side=tk.RIGHT)
        
        ttk.Scale(bright_frame, from_=30, to=100, variable=self.brightness_var,
                 command=self.on_bright_change).pack(fill=tk.X, pady=5)
        
        # 提醒
        remind_frame = ttk.LabelFrame(main, text="休息提醒", padding="12")
        remind_frame.pack(fill=tk.X, pady=(0, 12))
        
        ttk.Checkbutton(remind_frame, text="启用定时休息提醒", variable=self.reminder_var,
                       command=self.save_config).pack(anchor=tk.W)
        
        interval_row = ttk.Frame(remind_frame)
        interval_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(interval_row, text="间隔:").pack(side=tk.LEFT)
        ttk.Spinbox(interval_row, from_=15, to=120, width=6, textvariable=self.interval_var,
                   command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Label(interval_row, text="分钟").pack(side=tk.LEFT)
        
        self.remind_label = ttk.Label(remind_frame, text="", foreground="gray")
        self.remind_label.pack(anchor=tk.W, pady=(8, 0))
        
        # 其他
        other_frame = ttk.LabelFrame(main, text="其他", padding="12")
        other_frame.pack(fill=tk.X, pady=(0, 12))
        
        tray_state = "normal" if TRAY_AVAILABLE else "disabled"
        ttk.Checkbutton(other_frame, text="最小化到系统托盘", variable=self.minimize_var,
                       command=self.save_config, state=tray_state).pack(anchor=tk.W)
        
        # 按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Button(btn_frame, text="恢复默认", command=self.reset).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="关于", command=self.about).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="退出", command=self.quit_app).pack(side=tk.RIGHT)
    
    def toggle_eye_care(self):
        self.config["enabled"] = self.enabled_var.get()
        if self.config["enabled"]:
            self.apply_settings()
        else:
            self.gamma.restore_default()
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
    
    def apply_settings(self):
        self.gamma.set_gamma(self.config["temperature"], self.config["brightness"])
    
    def reset(self):
        self.temp_var.set(6500)
        self.brightness_var.set(100)
        self.enabled_var.set(False)
        self.config.update({"temperature": 6500, "brightness": 100, "enabled": False})
        self.temp_label.config(text="6500K")
        self.bright_label.config(text="100%")
        self.gamma.restore_default()
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
            self.remind_label.config(text=f"下次提醒: {int(left//60):02d}:{int(left%60):02d}")
    
    def show_reminder(self):
        def show():
            win = tk.Toplevel(self.root)
            win.title("休息提醒")
            win.geometry("400x240")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            
            win.update_idletasks()
            x = (win.winfo_screenwidth() - 400) // 2
            y = (win.winfo_screenheight() - 240) // 2
            win.geometry(f"+{x}+{y}")
            
            f = ttk.Frame(win, padding="30")
            f.pack(fill=tk.BOTH, expand=True)
            
            ttk.Label(f, text="👀", font=("Segoe UI Emoji", 50)).pack()
            ttk.Label(f, text="该让眼睛休息一下了！", font=("Microsoft YaHei UI", 16, "bold")).pack(pady=10)
            ttk.Label(f, text="建议远眺20秒，活动一下身体", font=("Microsoft YaHei UI", 10)).pack()
            ttk.Button(f, text="好的", command=win.destroy, width=12).pack(pady=15)
            
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
            pystray.MenuItem("显示", lambda: self.root.after(0, self.show_win), default=True),
            pystray.MenuItem("护眼模式", lambda: self.root.after(0, self.tray_toggle),
                           checked=lambda _: self.config["enabled"]),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self.root.after(0, self.quit_app))
        )
        
        self.tray_icon = pystray.Icon("护眼卫士", make_icon(), "护眼卫士", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
    
    def tray_toggle(self):
        self.enabled_var.set(not self.enabled_var.get())
        self.toggle_eye_care()
    
    def show_win(self):
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
        messagebox.showinfo("关于", f"""护眼卫士 v{self.VERSION}

🛡️ 功能:
  • 色温调节 2400K-6500K
  • 亮度调节 30%-100%
  • 定时休息提醒
  • 系统托盘

💡 建议:
  日间 5500-6500K
  夜间 3500-4500K
  深夜 2400-3500K

🔗 GitHub Actions 自动构建
© 2025""")
    
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
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def run(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 430) // 2
        y = (self.root.winfo_screenheight() - 580) // 2
        self.root.geometry(f"+{x}+{y}")
        self.root.mainloop()


def main():
    # 单实例
    import socket
    try:
        global _sock
        _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _sock.bind(('127.0.0.1', 52846))
    except:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("提示", "护眼卫士已在运行！")
        sys.exit(0)
    
    EyeCareApp().run()


if __name__ == "__main__":
    main()
