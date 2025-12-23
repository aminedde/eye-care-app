# -*- coding: utf-8 -*-
"""
护眼卫士 v1.1 - 修复色温和亮度问题
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
    """改进的屏幕Gamma控制器 - 修复色温和亮度问题"""
    
    def __init__(self):
        if sys.platform != 'win32':
            self.supported = False
            return
        
        self.supported = True
        self.gdi32 = ctypes.windll.gdi32
        self.user32 = ctypes.windll.user32
        self.hdc = self.user32.GetDC(None)
    
    def _kelvin_to_rgb(self, kelvin):
        """
        更精确的色温转RGB算法
        基于 Tanner Helland 的算法，适用于 1000K - 40000K
        """
        temp = kelvin / 100.0
        
        # 计算红色
        if temp <= 66:
            red = 255
        else:
            red = temp - 60
            red = 329.698727446 * (red ** -0.1332047592)
            red = max(0, min(255, red))
        
        # 计算绿色
        if temp <= 66:
            green = temp
            green = 99.4708025861 * (green ** 0.1) - 161.1195681661 if temp > 1 else 0
        else:
            green = temp - 60
            green = 288.1221695283 * (green ** -0.0755148492)
        green = max(0, min(255, green))
        
        # 计算蓝色
        if temp >= 66:
            blue = 255
        elif temp <= 19:
            blue = 0
        else:
            blue = temp - 10
            blue = 138.5177312231 * (blue ** 0.1) - 305.0447927307 if blue > 0 else 0
        blue = max(0, min(255, blue))
        
        return red / 255.0, green / 255.0, blue / 255.0
    
    def _calculate_luminance(self, r, g, b):
        """计算相对亮度（人眼感知）"""
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    
    def set_gamma(self, temperature=6500, brightness=100, compensate_brightness=True):
        """
        设置屏幕Gamma
        
        参数:
            temperature: 色温 (1000-6500K)
            brightness: 亮度 (0-100%)
            compensate_brightness: 是否补偿色温导致的亮度损失
        """
        if not self.supported:
            return False
        
        # 获取色温对应的RGB比例
        r_ratio, g_ratio, b_ratio = self._kelvin_to_rgb(temperature)
        
        # 亮度补偿：保持感知亮度不变
        if compensate_brightness and temperature < 6500:
            # 计算当前色温的相对亮度
            current_luminance = self._calculate_luminance(r_ratio, g_ratio, b_ratio)
            # 6500K时的亮度作为基准
            base_luminance = self._calculate_luminance(1.0, 1.0, 1.0)
            
            # 计算补偿系数（限制最大补偿为1.5倍，避免过曝）
            if current_luminance > 0:
                compensation = min(1.5, base_luminance / current_luminance)
                # 应用补偿（但不超过1.0）
                r_ratio = min(1.0, r_ratio * compensation)
                g_ratio = min(1.0, g_ratio * compensation)
                b_ratio = min(1.0, b_ratio * compensation)
        
        # 应用用户亮度设置
        brightness_factor = brightness / 100.0
        
        # 创建Gamma Ramp
        ramp = (ctypes.c_ushort * 256 * 3)()
        
        for i in range(256):
            # 基础值
            base = i * 256
            
            # 应用亮度
            base = int(base * brightness_factor)
            
            # 应用色温（使用gamma曲线使过渡更平滑）
            ramp[0][i] = min(65535, max(0, int(base * r_ratio)))  # Red
            ramp[1][i] = min(65535, max(0, int(base * g_ratio)))  # Green
            ramp[2][i] = min(65535, max(0, int(base * b_ratio)))  # Blue
        
        result = self.gdi32.SetDeviceGammaRamp(self.hdc, ctypes.byref(ramp))
        return result != 0
    
    def restore_default(self):
        """恢复默认Gamma"""
        return self.set_gamma(6500, 100, compensate_brightness=False)
    
    def cleanup(self):
        """清理资源"""
        if self.supported:
            self.restore_default()
            if self.hdc:
                self.user32.ReleaseDC(None, self.hdc)


class EyeCareApp:
    """护眼软件主程序"""
    
    VERSION = "1.1.0"
    
    def __init__(self):
        self.config_file = os.path.join(APP_PATH, "eye_care_config.json")
        self.gamma = GammaController()
        self.running = True
        self.tray_icon = None
        self.last_reminder = time.time()
        
        # 默认配置
        self.config = {
            "enabled": True,
            "temperature": 5000,
            "brightness": 100,          # 亮度默认100%
            "brightness_compensation": True,  # 亮度补偿默认开启
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
        self.root.geometry("450x650")
        self.root.resizable(False, False)
        
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass
        
        # 变量绑定
        self.enabled_var = tk.BooleanVar(value=self.config["enabled"])
        self.temp_var = tk.IntVar(value=self.config["temperature"])
        self.brightness_var = tk.IntVar(value=self.config["brightness"])
        self.compensation_var = tk.BooleanVar(value=self.config.get("brightness_compensation", True))
        self.reminder_var = tk.BooleanVar(value=self.config["reminder_enabled"])
        self.interval_var = tk.IntVar(value=self.config["reminder_interval"])
        self.minimize_var = tk.BooleanVar(value=self.config["minimize_to_tray"])
        
        self.create_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_ui(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Value.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Subtitle.TLabel", font=("Microsoft YaHei UI", 9), foreground="gray")
        style.configure("Info.TLabel", font=("Microsoft YaHei UI", 9), foreground="#666")
        
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
        
        # 色温调节
        temp_frame = ttk.LabelFrame(main, text="色温调节", padding="12")
        temp_frame.pack(fill=tk.X, pady=(0, 12))
        
        temp_header = ttk.Frame(temp_frame)
        temp_header.pack(fill=tk.X)
        ttk.Label(temp_header, text="色温:").pack(side=tk.LEFT)
        self.temp_label = ttk.Label(temp_header, text=f"{self.temp_var.get()}K", style="Value.TLabel")
        self.temp_label.pack(side=tk.RIGHT)
        
        # 色温滑块 - 范围扩展到 1900K
        self.temp_scale = ttk.Scale(temp_frame, from_=1900, to=6500, variable=self.temp_var,
                                    command=self.on_temp_change)
        self.temp_scale.pack(fill=tk.X, pady=5)
        
        hint_frame = ttk.Frame(temp_frame)
        hint_frame.pack(fill=tk.X)
        ttk.Label(hint_frame, text="🔥 暖色 1900K", foreground="#FF5722", font=("", 8)).pack(side=tk.LEFT)
        ttk.Label(hint_frame, text="❄️ 冷色 6500K", foreground="#03A9F4", font=("", 8)).pack(side=tk.RIGHT)
        
        # 色温预设按钮
        preset_frame = ttk.Frame(temp_frame)
        preset_frame.pack(fill=tk.X, pady=(10, 0))
        
        presets = [
            ("🕯️ 烛光", 1900),
            ("🔥 壁炉", 2400),
            ("💡 暖灯", 3400),
            ("☀️ 日光", 6500),
        ]
        for text, temp in presets:
            btn = ttk.Button(preset_frame, text=text, width=9,
                           command=lambda t=temp: self.set_temp(t))
            btn.pack(side=tk.LEFT, padx=2, expand=True)
        
        # 色温说明
        ttk.Label(temp_frame, text="提示: 夜间建议2400-3400K，白天建议5000-6500K", 
                 style="Info.TLabel").pack(anchor=tk.W, pady=(8, 0))
        
        # 亮度调节
        bright_frame = ttk.LabelFrame(main, text="亮度调节", padding="12")
        bright_frame.pack(fill=tk.X, pady=(0, 12))
        
        bright_header = ttk.Frame(bright_frame)
        bright_header.pack(fill=tk.X)
        ttk.Label(bright_header, text="亮度:").pack(side=tk.LEFT)
        self.bright_label = ttk.Label(bright_header, text=f"{self.brightness_var.get()}%", style="Value.TLabel")
        self.bright_label.pack(side=tk.RIGHT)
        
        ttk.Scale(bright_frame, from_=20, to=100, variable=self.brightness_var,
                 command=self.on_bright_change).pack(fill=tk.X, pady=5)
        
        # 亮度补偿选项
        ttk.Checkbutton(bright_frame, text="自动补偿色温导致的亮度变化", 
                       variable=self.compensation_var,
                       command=self.on_compensation_change).pack(anchor=tk.W, pady=(5, 0))
        ttk.Label(bright_frame, text="开启后，降低色温不会使屏幕变暗", 
                 style="Info.TLabel").pack(anchor=tk.W)
        
        # 休息提醒
        remind_frame = ttk.LabelFrame(main, text="休息提醒", padding="12")
        remind_frame.pack(fill=tk.X, pady=(0, 12))
        
        ttk.Checkbutton(remind_frame, text="启用定时休息提醒", variable=self.reminder_var,
                       command=self.save_config).pack(anchor=tk.W)
        
        interval_row = ttk.Frame(remind_frame)
        interval_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(interval_row, text="提醒间隔:").pack(side=tk.LEFT)
        ttk.Spinbox(interval_row, from_=15, to=120, width=6, textvariable=self.interval_var,
                   command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Label(interval_row, text="分钟").pack(side=tk.LEFT)
        
        self.remind_label = ttk.Label(remind_frame, text="", foreground="gray")
        self.remind_label.pack(anchor=tk.W, pady=(8, 0))
        
        # 其他设置
        other_frame = ttk.LabelFrame(main, text="其他设置", padding="12")
        other_frame.pack(fill=tk.X, pady=(0, 12))
        
        tray_state = "normal" if TRAY_AVAILABLE else "disabled"
        ttk.Checkbutton(other_frame, text="关闭窗口时最小化到系统托盘", 
                       variable=self.minimize_var,
                       command=self.save_config, state=tray_state).pack(anchor=tk.W)
        if not TRAY_AVAILABLE:
            ttk.Label(other_frame, text="(需要安装pystray库)", foreground="gray").pack(anchor=tk.W)
        
        # 底部按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Button(btn_frame, text="恢复默认", command=self.reset).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="关于", command=self.about).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="退出程序", command=self.quit_app).pack(side=tk.RIGHT)
    
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
    
    def on_compensation_change(self):
        self.config["brightness_compensation"] = self.compensation_var.get()
        if self.enabled_var.get():
            self.apply_settings()
        self.save_config()
    
    def apply_settings(self):
        self.gamma.set_gamma(
            temperature=self.config["temperature"],
            brightness=self.config["brightness"],
            compensate_brightness=self.config.get("brightness_compensation", True)
        )
    
    def reset(self):
        self.temp_var.set(6500)
        self.brightness_var.set(100)
        self.enabled_var.set(False)
        self.compensation_var.set(True)
        self.config.update({
            "temperature": 6500,
            "brightness": 100,
            "enabled": False,
            "brightness_compensation": True
        })
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
            mins = int(left // 60)
            secs = int(left % 60)
            self.remind_label.config(text=f"距离下次提醒: {mins:02d}:{secs:02d}")
    
    def show_reminder(self):
        def show():
            win = tk.Toplevel(self.root)
            win.title("休息提醒")
            win.geometry("420x260")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            
            win.update_idletasks()
            x = (win.winfo_screenwidth() - 420) // 2
            y = (win.winfo_screenheight() - 260) // 2
            win.geometry(f"+{x}+{y}")
            
            f = ttk.Frame(win, padding="30")
            f.pack(fill=tk.BOTH, expand=True)
            
            ttk.Label(f, text="👀", font=("Segoe UI Emoji", 48)).pack()
            ttk.Label(f, text="该让眼睛休息一下了！", 
                     font=("Microsoft YaHei UI", 16, "bold")).pack(pady=10)
            ttk.Label(f, text="建议：看看远处，闭眼休息20秒，活动一下身体", 
                     font=("Microsoft YaHei UI", 10)).pack()
            ttk.Button(f, text="我知道了", command=win.destroy, width=15).pack(pady=15)
            
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
            pystray.MenuItem("显示窗口", lambda: self.root.after(0, self.show_win), default=True),
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

🛡️ 功能特性:
  • 色温调节 1900K - 6500K
  • 亮度调节 20% - 100%
  • 自动亮度补偿
  • 定时休息提醒
  • 系统托盘后台运行

💡 色温建议:
  • 日间办公: 5500K - 6500K
  • 傍晚使用: 4000K - 5000K  
  • 夜间使用: 3000K - 4000K
  • 深夜护眼: 1900K - 2700K

🔧 v1.1 更新:
  • 扩展色温范围至1900K
  • 修复低色温不变化问题
  • 添加亮度补偿功能

© 2025 护眼卫士""")
    
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
            self.config["brightness_compensation"] = self.compensation_var.get()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def run(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 450) // 2
        y = (self.root.winfo_screenheight() - 650) // 2
        self.root.geometry(f"+{x}+{y}")
        self.root.mainloop()


def main():
    # 单实例检测
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
    main()        self.config_file = os.path.join(APP_PATH, "eye_care_config.json")
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
