import os
import sys
import math
import asyncio
import edge_tts
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import VideoClip, AudioFileClip, concatenate_videoclips

# ==========================================
# 1. 爆款场景与动态终端指令配置
# ==========================================
SCENES = [
    {
        "hud_title": "SYSTEM ALERT: HARDFAULT DETECTED",
        "badge": "🚨 传统嵌入式痛点",
        "voice": "写单片机代码还在通宵查哈德福特吗？最头疼的时钟配错、引脚复用冲突、寄存器死锁，现在全部有解了！",
        "terminal_lines": [
            "[!] HARDFAULT EXCEPTION AT 0x080012C4",
            "[-] SCB->CFSR: INVSTATE (Invalid State)",
            "[-] RCC->CR: HSE Oscillator NOT Stable",
            "[x] System Lockup. Debugger disconnected."
        ],
        "sub_title": "时钟错乱 · 引脚冲突 · 寄存器死锁",
        "color_theme": (239, 68, 68) # 红色警报
    },
    {
        "hud_title": "AI COPILOT: HARDWARE INTERVIEW",
        "badge": "💡 第一性原理 · 架构对齐",
        "voice": "隆重推荐开源神器：STM32 硬件在环自愈套件！AI 自动深度访谈，排查引脚冲突，生成小白防呆接线图，你只需照图插线。",
        "terminal_lines": [
            ">> Running Grill-Me 5-Stage Interview...",
            ">> [1/5] HSE Clock Tree -> Set to 8MHz Crystal",
            ">> [2/5] Pin Check -> USART1 vs TIM2 Remap OK",
            ">> [OK] Generated Wiring Guide: 100% Plug & Play"
        ],
        "sub_title": "5大硬件决策访谈 · 小白防呆接线",
        "color_theme": (56, 189, 248) # 科技蓝
    },
    {
        "hud_title": "AUTO HEALING: KEIL & JTAG IN-THE-LOOP",
        "badge": "⚡ 在环自愈 · 0-Error 闭环",
        "voice": "更绝的是，它全程接管代码编写，自动调用 Keil 进行零报错编译自愈，配合探针免交互在线烧录，自动嗅探串口与寄存器！",
        "terminal_lines": [
            ">> Executing Keil uVision Automated Build...",
            ">> Build Status: 0 Error(s), 0 Warning(s) [PASS]",
            ">> Probing JTAG/SWD Debugger -> Target STM32F103",
            ">> CPU Alive Telemetry: Core Running [100%]"
        ],
        "sub_title": "Keil 0-Error 自愈 · JTAG 免阻塞烧录",
        "color_theme": (34, 197, 94) # 极客绿
    },
    {
        "hud_title": "GITHUB REPO: OPEN SOURCE NOW",
        "badge": "🌟 极客开源 · 立即体验",
        "voice": "项目现已完全开源，GitHub 搜索 TaoCosmo-Dev，赶紧点赞收藏加关注，去 Star 体验吧！",
        "terminal_lines": [
            "-------------------------------------------",
            " GitHub : TaoCosmo-Dev/STM32_AutoDebug_Kit ",
            " Stars  : ⭐ Welcome to Fork & Star!      ",
            " Status : Open Source & Ready to Deploy    ",
            "-------------------------------------------"
        ],
        "sub_title": "GitHub 搜索: TaoCosmo-Dev",
        "color_theme": (251, 191, 36) # 活力黄
    }
]

# ==========================================
# 2. 字体与高保真动效渲染引擎
# ==========================================
def get_font(size):
    font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "C:\\Windows\\Fonts\\msyh.ttc",
        "C:\\Windows\\Fonts\\simhei.ttf"
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def render_dynamic_frame(t, scene, total_dur, w=1080, h=1920):
    img = Image.new("RGB", (w, h), color=(10, 14, 23))
    draw = ImageDraw.Draw(img)

    # 1. 动态流动赛博朋克网格 (向下缓缓移动)
    grid_spacing = 60
    y_offset = int((t * 40) % grid_spacing)
    for y in range(0, h, grid_spacing):
        draw.line([(0, y + y_offset), (w, y + y_offset)], fill=(18, 24, 38), width=1)
    for x in range(0, w, grid_spacing):
        draw.line([(x, 0), (x, h)], fill=(18, 24, 38), width=1)

    # 2. 动态激光扫描线 (从上往下扫)
    scan_y = int((t * 300) % h)
    draw.line([(0, scan_y), (w, scan_y)], fill=(56, 189, 248), width=2)
    if scan_y > 10:
        draw.line([(0, scan_y - 4), (w, scan_y - 4)], fill=(20, 80, 140), width=1)

    theme_color = scene["color_theme"]
    font_tag = get_font(36)
    font_hud = get_font(30)
    font_code = get_font(34)
    font_sub = get_font(48)
    font_author = get_font(32)

    # 3. 顶部 HUD 状态栏 (轻微呼吸呼吸光)
    glow_alpha = int(180 + 75 * math.sin(t * 4))
    draw.rectangle([(60, 140), (1020, 230)], fill=(15, 23, 42), outline=theme_color, width=3)
    draw.text((90, 162), f"⚡ {scene['badge']}", fill=theme_color, font=font_tag)

    # 4. 主视觉：动态黑客终端卡片 (平滑缓入动画 + 终端实时敲击)
    enter_progress = min(1.0, t / 0.4) # 0.4秒内弹性滑入
    card_y = int(300 + (1.0 - enter_progress) * 80)
    
    # 终端卡片主体
    draw.rectangle([(60, card_y), (1020, card_y + 980)], fill=(13, 17, 28), outline=(51, 65, 85), width=2)
    # 终端顶部操作栏
    draw.rectangle([(60, card_y), (1020, card_y + 60)], fill=(30, 41, 59))
    # 终端红黄绿圆点
    draw.ellipse([(85, card_y + 20), (105, card_y + 40)], fill=(239, 68, 68))
    draw.ellipse([(120, card_y + 20), (140, card_y + 40)], fill=(234, 179, 8))
    draw.ellipse([(155, card_y + 20), (175, card_y + 40)], fill=(34, 197, 94))
    draw.text((200, card_y + 15), scene["hud_title"], fill=(148, 163, 184), font=font_hud)

    # 5. 终端打字机动画 (随时间逐字输出代码)
    full_text = "\n\n".join(scene["terminal_lines"])
    total_chars = len(full_text)
    type_speed = 35 # 每秒敲击字数
    visible_chars = min(total_chars, int(t * type_speed))
    current_text = full_text[:visible_chars]
    
    # 绘制终端代码
    text_y = card_y + 100
    for line in current_text.split("\n"):
        if line.startswith("[!]") or line.startswith("[x]") or line.startswith("[-]"):
            color = (248, 113, 113) # 警告红
        elif line.startswith(">>") or line.startswith("[+]") or line.startswith("[OK]"):
            color = (74, 222, 128) # 极客绿
        else:
            color = (226, 232, 240)
        draw.text((100, text_y), line, fill=color, font=font_code)
        text_y += 54

    # 闪烁光标 █
    if int(t * 3) % 2 == 0 and visible_chars < total_chars + 10:
        draw.text((100, text_y), "█", fill=theme_color, font=font_code)

    # 6. 中部核心爆款大字幕 (随着语音跳动放大)
    pulse_scale = 1.0 + 0.03 * math.sin(t * 6)
    draw.rectangle([(60, card_y + 1040), (1020, card_y + 1180)], fill=(30, 41, 59), outline=theme_color, width=2)
    draw.text((100, card_y + 1070), scene["sub_title"], fill=(255, 255, 255), font=font_sub)

    # 7. 底部动态频谱 HUD (随节奏跳动)
    spectrum_base_y = 1750
    draw.text((90, 1660), "STM32 HARDWARE COPILOT // AUDIO SPECTRUM", fill=(100, 116, 139), font=font_hud)
    num_bars = 28
    bar_w = 26
    for i in range(num_bars):
        bar_h = int(25 + 50 * math.sin(t * 8 + i * 0.5) * math.cos(t * 4 - i * 0.3))
        bar_x = 90 + i * (bar_w + 6)
        draw.rectangle([(bar_x, spectrum_base_y - abs(bar_h)), (bar_x + bar_w, spectrum_base_y)], fill=theme_color)

    # 8. 底部作者水印
    draw.rectangle([(60, 1800), (1020, 1870)], fill=(15, 23, 42))
    draw.text((100, 1815), "👨‍💻 GitHub: TaoCosmo-Dev  |  STM32_AutoDebug_Kit", fill=(148, 163, 184), font=font_author)

    return np.array(img)

# ==========================================
# 3. 语音合成与 60/24fps 动效剪辑合成
# ==========================================
async def generate_voice(text, filename):
    communicate = edge_tts.Communicate(text, voice="zh-CN-YunxiNeural", rate="+15%")
    await communicate.save(filename)

def build_dynamic_video():
    clips = []
    temp_files = []

    print("🚀 [1/3] 开始生成场景语音与动态极客 HUD 渲染...")
    for idx, scene in enumerate(SCENES):
        audio_file = f"temp_voice_{idx}.mp3"
        temp_files.append(audio_file)
        
        print(f"   -> [场景 {idx+1}] 正在合成配音: {scene['badge']}")
        asyncio.run(generate_voice(scene["voice"], audio_file))
        audio_clip = AudioFileClip(audio_file)
        duration = audio_clip.duration

        # 动态帧生成器
        def make_frame(t, current_scene=scene, dur=duration):
            return render_dynamic_frame(t, current_scene, dur)

        vclip = VideoClip(make_frame, duration=duration).set_audio(audio_clip)
        clips.append(vclip)

    print("🎬 [2/3] 拼接场景与音频轨道...")
    final_video = concatenate_videoclips(clips, method="compose")

    print("⚡ [3/3] 正在导出 1080x1920 动态短视频 (douyin_stm32_video.mp4)...")
    final_video.write_videofile(
        "douyin_stm32_video.mp4",
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=4
    )

    for c in clips:
        c.close()
    final_video.close()

    for f in temp_files:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    print("✅ 动态短视频生成完毕！已生成在: douyin_stm32_video.mp4")

if __name__ == "__main__":
    build_dynamic_video()
