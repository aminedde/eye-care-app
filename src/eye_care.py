# -*- coding: utf-8 -*-
"""
护眼卫士 v1.4 - 修复色温和亮度问题
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
        色温转RGB - Tanner Helland算法
        """
        kelvin = max(1000, min(40000, kelvin))
        temp = kelvin / 100.0
        
        if temp <= 66:
            red = 255.0
        else:
            red = temp - 60
            red = 329.698727446 * math.pow(red, -0.1332047592)
            red = max(0, min(255, red))
        
        if temp <= 66:
            if temp <= 1:
                green = 0
            else:
                green = 99.4708025861 * math.log(temp) - 161.1195681661
        else:
            green = temp - 60
            green = 288.1221695283 * math.pow(green, -0.0755148492)
        green = max(0, min(255, green))
        
        if temp >= 66:
            blue = 255.0
        elif temp <= 19:
            blue = 0.0
        else:
            blue = temp - 10
            blue = 138.5177312231 * math.log(blue) - 305.0447927307
            blue = max(0, min(255, blue))
        
        return red / 255.0, green / 255.0, blue / 255.0

    def set_gamma(self, temperature=6500, brightness=100, strength=70):
        """
        设置屏幕Gamma
        temperature: 色温 (K)
        brightness: 亮度 (%)
        strength: 色温效果强度 (%)
        """
        if not self.supported:
            return False
        
        hdc = self.user32.GetDC(None)
        if not hdc:
            return False
        
        try:
            # 获取色温RGB
            r, g, b = self.kelvin_to_rgb(temperature)
            
            # 限制效果强度 (与白色混合)
            # strength=100 表示完全应用色温，strength=0 表示纯白
            s = strength / 100.0
            r = 1.0 - (1.0 - r) * s
            g = 1.0 - (1.0 - g) * s
            b = 1.0 - (1.0 - b) * s
            
            # 亮度补偿：将最大通道归一化到1.0，防止变暗
            max_channel = max(r, g, b)
            if max_channel > 0.01:
                r = r / max_channel
                g = g / max_channel
                b = b / max_channel
            
            # 应用用户亮度设置
            bf = brightness / 100.0
            r = r * bf
            g = g * bf
            b = b * bf
            
            # 创建Gamma Ramp
            ramp = (ctypes.c_ushort * 256 * 3)()
            for i in range(256):
                ramp[0][i] = min(65535, int(i * 256 * r))
                ramp[1][i] = min(65535, int(i * 256 * g))
                ramp[2][i] = min(65535, int(i * 256 * b))
            
            result = self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
            return bool(result)
            
        finally:
            self.user32.ReleaseDC(None, hdc)

    def restore(self):
        """恢复默认"""
        if not self.supported:
            return False
        
        hdc = self.user32.GetDC(None)
        if not hdc:
            return False
        
        try:
            ramp = (ctypes.c_ushort * 256 * 3)()
            for i in range(256):
                val = i * 256
                ramp[0][i] = val
                ramp[1][i] = val
                ramp[2][i] = val
            return bool(self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
        finally:
            self.user32.ReleaseDC(None, hdc)


class EyeCareApp:
    """护眼软件主程序"""
    
    VERSION = "1.4.0"

    def __init__(self):
        self.config_file = os.path.join(APP_PATH, "eye_care_config.json")
        self.gamma = GammaController()
        self.running = True
        self.tray_icon = None
        self.last_reminder = time.time()
        
        self.config = {
            "enabled": True,
            "temperature": 5500,
            "brightness": 100,
            "strength": 70,
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
        self.root.geometry("420x600")
        self.root.resizable(False, False)
        
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass
        
        self.enabled_var = tk.BooleanVar(value=self.config["enabled"])
        self.temp_var = tk.IntVar(value=self.config["temperature"])
        self.brightness_var = tk.IntVar(value=self.config["brightness"])
        self.strength_var = tk.IntVar(value=self.config.get("strength", 70))
        self.reminder_var = tk.BooleanVar(value=self.config["reminder_enabled"])
        self.interval_var = tk.IntVar(value=self.config["reminder_interval"])
        self.minimize_var = tk.BooleanVar(value=self.config["minimize_to_tray"])
        
        self.create_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_ui(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Value.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        
        main = ttk.Frame(self.root, padding="15")
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="护眼卫士", style="Title.TLabel").pack(pady=(0, 12))

        # 开关
        switch_frame = ttk.LabelFrame(main, text="护眼模式", padding="8")
        switch_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Checkbutton(switch_frame, text="启用护眼模式", variable=self.enabled_var,
                        command=self.toggle_eye_care).pack(anchor=tk.W)

        # 色温
        temp_frame = ttk.LabelFrame(main, text="色温调节", padding="8")
        temp_frame.pack(fill=tk.X, pady=(0, 8))
        
        temp_header = ttk.Frame(temp_frame)
        temp_header.pack(fill=tk.X)
        ttk.Label(temp_header, text="色温:").pack(side=tk.LEFT)
        self.temp_label = ttk.Label(temp_header, text=f"{self.temp_var.get()}K", style="Value.TLabel")
        self.temp_label.pack(side=tk.RIGHT)
        
        self.temp_scale = ttk.Scale(temp_frame, from_=3200, to=6500, 
                                    variable=self.temp_var, command=self.on_temp_change)
        self.temp_scale.pack(fill=tk.X, pady=5)
        
        hint_frame = ttk.Frame(temp_frame)
        hint_frame.pack(fill=tk.X)
        ttk.Label(hint_frame, text="暖 3200K", foreground="#E65100", font=("", 8)).pack(side=tk.LEFT)
        ttk.Label(hint_frame, text="冷 6500K", foreground="#0288D1", font=("", 8)).pack(side=tk.RIGHT)
        
        # 预设按钮
        preset_frame = ttk.Frame(temp_frame)
        preset_frame.pack(fill=tk.X, pady=(8, 0))
        presets = [("暖光", 3200), ("夜间", 4000), ("阅读", 5000), ("日光", 6500)]
        for text, temp in presets:
            btn = ttk.Button(preset_frame, text=text, width=7,
                            command=lambda t=temp: self.set_temp_preset(t))
            btn.pack(side=tk.LEFT, padx=2, expand=True)

        # 效果强度
        strength_frame = ttk.LabelFrame(main, text="效果强度", padding="8")
        strength_frame.pack(fill=tk.X, pady=(0, 8))
        
        strength_header = ttk.Frame(strength_frame)
        strength_header.pack(fill=tk.X)
        ttk.Label(strength_header, text="强度:").pack(side=tk.LEFT)
        self.strength_label = ttk.Label(strength_header, text=f"{self.strength_var.get()}%", style="Value.TLabel")
        self.strength_label.pack(side=tk.RIGHT)
        
        ttk.Scale(strength_frame, from_=30, to=100, variable=self.strength_var,
                  command=self.on_strength_change).pack(fill=tk.X, pady=5)
        
        ttk.Label(strength_frame, text="强度越高色温效果越明显，建议50-80%", 
                 foreground="gray", font=("", 8)).pack(anchor=tk.W)

        # 亮度
        bright_frame = ttk.LabelFrame(main, text="亮度调节", padding="8")
        bright_frame.pack(fill=tk.X, pady=(0, 8))
        
        bright_header = ttk.Frame(bright_frame)
        bright_header.pack(fill=tk.X)
        ttk.Label(bright_header, text="亮度:").pack(side=tk.LEFT)
        self.bright_label = ttk.Label(bright_header, text=f"{self.brightness_var.get()}%", style="Value.TLabel")
        self.bright_label.pack(side=tk.RIGHT)
        
        ttk.Scale(bright_frame, from_=50, to=100, variable=self.brightness_var,
                  command=self.on_bright_change).pack(fill=tk.X, pady=5)

        # 休息提醒
        remind_frame = ttk.LabelFrame(main, text="休息提醒", padding="8")
        remind_frame.pack(fill=tk.X, pady=(0, 8))
        
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
        other_frame = ttk.LabelFrame(main, text="其他", padding="8")
        other_frame.pack(fill=tk.X, pady=(0, 8))
        
        tray_state = "normal" if TRAY_AVAILABLE else "disabled"
        ttk.Checkbutton(other_frame, text="关闭时最小化到托盘",
                        variable=self.minimize_var, command=self.save_config,
                        state=tray_state).pack(anchor=tk.W)

        # 按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_frame, text="恢复默认", command=self.reset).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="关于", command=self.about).pack(side=tk.LEFT, padx=8)
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

    def set_temp_preset(self, temp):
        """预设按钮"""
        self.temp_var.set(temp)
        self.temp_label.config(text=f"{temp}K")
        self.config["temperature"] = temp
        
        if not self.enabled_var.get():
            self.enabled_var.set(True)
            self.config["enabled"] = True
        
        self.apply_settings()
        self.save_config()

    def on_strength_change(self, val):
        strength = int(float(val))
        self.strength_var.set(strength)
        self.strength_label.config(text=f"{strength}%")
        self.config["strength"] = strength
        if self.enabled_var.get():
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
        """应用当前设置"""
        self.gamma.set_gamma(
            temperature=self.config["temperature"],
            brightness=self.config["brightness"],
            strength=self.config.get("strength", 70)
        )

    def reset(self):
        self.temp_var.set(6500)
        self.brightness_var.set(100)
        self.strength_var.set(70)
        self.enabled_var.set(False)
        
        self.config.update({
            "temperature": 6500,
            "brightness": 100,
            "strength": 70,
            "enabled": False
        })
        
        self.temp_label.config(text="6500K")
        self.bright_label.config(text="100%")
        self.strength_label.config(text="70%")
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
            win.geometry("350x180")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            win.update_idletasks()
            x = (win.winfo_screenwidth() - 350) // 2
            y = (win.winfo_screenheight() - 180) // 2
            win.geometry(f"+{x}+{y}")
            
            f = ttk.Frame(win, padding="20")
            f.pack(fill=tk.BOTH, expand=True)
            ttk.Label(f, text="休息一下", font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(0, 8))
            ttk.Label(f, text="您已连续使用电脑较长时间").pack()
            ttk.Label(f, text="建议看看远处，活动一下").pack(pady=5)
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
            d.ellipse([14, 24, 50, 40], fill='white')
            d.ellipse([27, 28, 37, 36], fill='#333')
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

功能:
• 色温调节 3200K-6500K
• 效果强度 30%-100%
• 亮度调节 50%-100%
• 定时休息提醒
• 系统托盘运行

使用建议:
• 日间: 5500-6500K, 强度50%
• 傍晚: 4500-5500K, 强度60%
• 夜间: 3500-4500K, 强度70%
• 深夜: 3200-3500K, 强度80%""")

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
            self.config["strength"] = self.strength_var.get()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except:
            pass

    def run(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 420) // 2
        y = (self.root.winfo_screenheight() - 600) // 2
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
