import os
import sys
import math
import asyncio
import edge_tts
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import VideoClip, AudioFileClip, concatenate_videoclips

# ==========================================
# 1. 核心主题文案配置：不用打开 Keil 和 CubeMX 的全流程开发
# ==========================================
SCENES = [
    {
        "type": "pain",
        "badge": "🚫 传统嵌入式痛点",
        "title": "还在手动点 CubeMX 和 Keil？",
        "sub_title": "不用打开 CubeMX 和 Keil 搞定 STM32 全流程！",
        "voice": "玩单片机最烦什么？CubeMX点引脚点到眼花，Keil报错改到崩溃！现在开发STM32，你甚至连CubeMX和Keil都不用打开了！",
        "desc_lines": [
            "[!] 传统痛点 1: CubeMX 引脚时钟配置极其繁琐",
            "[!] 传统痛点 2: Keil 语法报错反复修改浪费生命",
            "[!] 传统痛点 3: 硬件死锁 HardFault 难以排查"
        ],
        "theme_color": (239, 68, 68) # 警报红
    },
    {
        "type": "cubemx_free",
        "badge": "⚡ 阶段 1: 免打开 STM32CubeMX",
        "title": "AI 自动对齐时钟与引脚复用",
        "sub_title": "自动生成小白防呆接线指南，照图插线即用",
        "voice": "第一步：不用打开CubeMX。AI自动执行硬件深度访谈，帮你排查晶振时钟树与引脚冲突，一秒生成小白防呆接线图，你只需照图插线！",
        "desc_lines": [
            ">> 晶振时钟树: 8MHz HSE -> 72MHz PLL 自动对齐",
            ">> 引脚冲突排查: USART1 / SPI2 / I2C1 零冲突",
            ">> 接线交付: 输出《杜邦线引脚对照表 + 电气安全预警》"
        ],
        "theme_color": (56, 189, 248) # 科技蓝
    },
    {
        "type": "keil_free",
        "badge": "💻 阶段 2: 免打开 Keil 编写代码",
        "title": "AI 自动编写 + 0-Error 闭环自愈",
        "sub_title": "后台无感调用 Keil 编译器，自动排错自愈",
        "voice": "第二步：不用打开Keil。AI智能体直接编写符合工业级规范的底层固件，并在后台无感调用Keil编译器，实现零报错自动循环自愈！",
        "desc_lines": [
            ">> 固件规范: 严格遵循 MISRA-C & BARR-C 工业标准",
            ">> 自动化构建: 后台调用 Keil ARMCC 全量编译",
            ">> 自愈结果: Build 0 Error(s), 0 Warning(s) [100% 通过]"
        ],
        "theme_color": (168, 85, 247) # 紫色极客
    },
    {
        "type": "debug_free",
        "badge": "📟 阶段 3: 免打开仿真器 烧录调试",
        "title": "JTAG 静默烧录 + 串口自动嗅探",
        "sub_title": "CPU 寄存器实时遥测，硬件在环全自动验收",
        "voice": "第三步：不用手动点下载调试。JTAG和SWD探针自动静默烧录，自动嗅探串口波特率与遥测CPU寄存器，硬件在环全自动验收！",
        "desc_lines": [
            ">> 探针自动仲裁: ST-Link / J-Link / DAP-Link 免死锁",
            ">> 串口自动嗅探: 波特率自适应嗅探与握手遥测",
            ">> CPU 存活确认: SCB->CFSR 寄存器遥测健康 [PASS]"
        ],
        "theme_color": (34, 197, 94) # 绿色通行
    },
    {
        "type": "summary",
        "badge": "🌟 全流程开源 · 立即体验",
        "title": "STM32 硬件在环固件自愈套件",
        "sub_title": "单片机开发效率提升 10 倍，GitHub 立即 Star！",
        "voice": "写代码、烧录、调试全流程一气呵成！GitHub搜索 TaoCosmo-Dev，赶紧点赞收藏，去体验单片机开发提速十倍的快感吧！",
        "desc_lines": [
            "--------------------------------------------------",
            " GitHub 仓库 : TaoCosmo-Dev/STM32_AutoDebug_Kit   ",
            " 核心价值    : 全流程开发 / 告别繁琐工具链         ",
            " 许可证      : Open Source (欢迎 Star & Fork)     ",
            "--------------------------------------------------"
        ],
        "theme_color": (251, 191, 36) # 金黄
    }
]

# ==========================================
# 2. 跨平台字体加载
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

# ==========================================
# 3. 动态视觉场景绘制器 (多场景穿插动效)
# ==========================================
def render_frame_by_scene(t, scene, dur, w=1080, h=1920):
    img = Image.new("RGB", (w, h), color=(10, 14, 23))
    draw = ImageDraw.Draw(img)
    theme_color = scene["theme_color"]

    # 1. 基础赛博背景
    for y in range(0, h, 8):
        ratio = y / h
        r = int(10 + 12 * ratio)
        g = int(14 + 18 * ratio)
        b = int(24 + 35 * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b), width=8)

    # 2. 动态激光扫描线
    scan_y = int((t * 260) % h)
    draw.line([(0, scan_y), (w, scan_y)], fill=theme_color, width=2)

    font_badge = get_font(36)
    font_title = get_font(52)
    font_sub = get_font(38)
    font_code = get_font(32)
    font_hud = get_font(28)

    # 3. 顶部 Header 标签
    draw.rectangle([(60, 130), (1020, 220)], fill=(20, 29, 47), outline=theme_color, width=3)
    draw.text((90, 150), f"⚡ {scene['badge']}", fill=theme_color, font=font_badge)

    # 4. 场景专属中央动效 (穿插不同视觉：PCB电路 / 示波器波形 / 终端自愈)
    card_y = 260

    if scene["type"] == "pain":
        # 痛点场景：红色脉冲闪烁 + 警告大字
        draw.rectangle([(60, card_y), (1020, card_y + 400)], fill=(30, 15, 20), outline=(239, 68, 68), width=3)
        draw.text((90, card_y + 40), "❌ 告别传统繁琐开发流程！", fill=(248, 113, 113), font=font_title)
        draw.text((90, card_y + 130), "• 无需打开 STM32CubeMX 点引脚", fill=(254, 202, 202), font=font_sub)
        draw.text((90, card_y + 200), "• 无需打开 Keil 反复调试排错", fill=(254, 202, 202), font=font_sub)
        draw.text((90, card_y + 270), "• 无需手动配置 JTAG/SWD 探针", fill=(254, 202, 202), font=font_sub)

    elif scene["type"] == "cubemx_free":
        # 免 CubeMX 场景：动态 PCB 电路走线脉冲
        draw.rectangle([(60, card_y), (1020, card_y + 400)], fill=(13, 27, 42), outline=(56, 189, 248), width=3)
        draw.text((90, card_y + 30), "🔹 芯片引脚与时钟树自动映射", fill=(56, 189, 248), font=font_title)
        # 绘制动态电路走线
        for i in range(5):
            line_y = card_y + 140 + i * 50
            draw.line([(90, line_y), (990, line_y)], fill=(30, 60, 90), width=3)
            # 沿导线流动的光点
            dot_x = int(90 + ((t * 200 + i * 150) % 900))
            draw.ellipse([(dot_x - 8, line_y - 8), (dot_x + 8, line_y + 8)], fill=(56, 189, 248))
            draw.text((90, line_y - 25), f"PIN_MAP_0{i}: GPIO/AF Mode Configured [AUTO]", fill=(148, 163, 184), font=font_hud)

    elif scene["type"] == "keil_free":
        # 免 Keil 场景：实时代码自愈与 0-Error 徽章
        draw.rectangle([(60, card_y), (1020, card_y + 400)], fill=(26, 16, 37), outline=(168, 85, 247), width=3)
        draw.text((90, card_y + 30), "🟣 Keil ARMCC 0-Error 闭环自愈", fill=(192, 132, 252), font=font_title)
        draw.rectangle([(90, card_y + 120), (990, card_y + 240)], fill=(48, 28, 70))
        draw.text((110, card_y + 140), "$ armcc --auto-fix --strict-misra firmware.c", fill=(233, 213, 255), font=font_code)
        draw.text((110, card_y + 190), ">> Output: 0 Error(s), 0 Warning(s) - Verified!", fill=(74, 222, 128), font=font_code)
        # 绿色 100% 进度条
        draw.rectangle([(90, card_y + 280), (990, card_y + 320)], fill=(40, 20, 60))
        prog_w = int(min(900, 900 * (t / max(1.0, dur - 0.5))))
        draw.rectangle([(90, card_y + 280), (90 + prog_w, card_y + 320)], fill=(168, 85, 247))
        draw.text((90, card_y + 335), "AI 固件自愈编译完成度: 100%", fill=(216, 180, 254), font=font_hud)

    elif scene["type"] == "debug_free":
        # 免 Debugger 场景：动态示波器双通道波形
        draw.rectangle([(60, card_y), (1020, card_y + 400)], fill=(10, 25, 20), outline=(34, 197, 94), width=3)
        draw.text((90, card_y + 25), "🟢 示波器波形与寄存器遥测", fill=(74, 222, 128), font=font_title)
        # 示波器网格
        for gy in range(card_y + 100, card_y + 380, 35):
            draw.line([(90, gy), (990, gy)], fill=(15, 45, 30), width=1)
        # 绘制正弦/PWM跳动波形
        points_ch1 = []
        points_ch2 = []
        for x in range(90, 990, 8):
            rad = (x * 0.03) + (t * 8)
            y1 = card_y + 190 + int(35 * math.sin(rad))
            y2 = card_y + 300 + (30 if math.sin(rad * 1.5) > 0 else -30)
            points_ch1.append((x, y1))
            points_ch2.append((x, y2))
        draw.line(points_ch1, fill=(56, 189, 248), width=3) # CH1 模拟波
        draw.line(points_ch2, fill=(251, 191, 36), width=3) # CH2 PWM方波
        draw.text((100, card_y + 105), "CH1: ADC DMA Sample (72MHz)", fill=(56, 189, 248), font=font_hud)
        draw.text((100, card_y + 345), "CH2: TIM1 PWM Output (100kHz)", fill=(251, 191, 36), font=font_hud)

    else:
        # 总结开源场景
        draw.rectangle([(60, card_y), (1020, card_y + 400)], fill=(28, 25, 15), outline=(251, 191, 36), width=3)
        draw.text((90, card_y + 40), "🌟 全流程极速交付，提速 10 倍！", fill=(251, 191, 36), font=font_title)
        draw.text((90, card_y + 140), "GitHub 搜索: TaoCosmo-Dev", fill=(254, 240, 138), font=font_sub)
        draw.text((90, card_y + 220), "项目: STM32_AutoDebug_Universal_Kit", fill=(254, 240, 138), font=font_sub)
        draw.text((90, card_y + 300), "⭐ 欢迎点赞、收藏、Star 体验！", fill=(250, 204, 21), font=font_sub)

    # 5. 下半部分：极客终端详细日志卡片
    term_y = 690
    draw.rectangle([(60, term_y), (1020, term_y + 700)], fill=(13, 17, 28), outline=(51, 65, 85), width=2)
    draw.rectangle([(60, term_y), (1020, term_y + 55)], fill=(30, 41, 59))
    draw.ellipse([(85, term_y + 18), (105, term_y + 38)], fill=(239, 68, 68))
    draw.ellipse([(120, term_y + 18), (140, term_y + 38)], fill=(234, 179, 8))
    draw.ellipse([(155, term_y + 18), (175, term_y + 38)], fill=(34, 197, 94))
    draw.text((200, term_y + 15), f"AUTO-WORKFLOW // {scene['badge']}", fill=(148, 163, 184), font=font_hud)

    # 终端文字打印
    line_y = term_y + 80
    for l in scene["desc_lines"]:
        if "[!]" in l:
            col = (248, 113, 113)
        elif ">>" in l:
            col = (74, 222, 128)
        else:
            col = (226, 232, 240)
        draw.text((90, line_y), l, fill=col, font=font_code)
        line_y += 65

    # 6. 核心爆款大字幕 (随时间呼吸跳动)
    sub_y = 1430
    draw.rectangle([(60, sub_y), (1020, sub_y + 140)], fill=(30, 41, 59), outline=theme_color, width=3)
    draw.text((90, sub_y + 40), scene["sub_title"], fill=(255, 255, 255), font=font_title)

    # 7. 底部动态跳动音波频谱
    spec_y = 1660
    draw.text((90, spec_y - 35), "AI HARDWARE COPILOT // AUDIO FREQUENCY", fill=(100, 116, 139), font=font_hud)
    for i in range(28):
        bh = int(20 + 45 * abs(math.sin(t * 8 + i * 0.4)))
        bx = 90 + i * 32
        draw.rectangle([(bx, spec_y + 50 - bh), (bx + 24, spec_y + 50)], fill=theme_color)

    # 8. 底部作者水印
    draw.rectangle([(60, 1780), (1020, 1860)], fill=(15, 23, 42))
    draw.text((90, 1800), "👨‍💻 GitHub: TaoCosmo-Dev  |  STM32_AutoDebug_Universal_Kit", fill=(148, 163, 184), font=font_badge)

    return np.array(img)

# ==========================================
# 4. 语音合成与视频剪辑全流程构建
# ==========================================
async def generate_voice(text, filename):
    communicate = edge_tts.Communicate(text, voice="zh-CN-YunxiNeural", rate="+15%")
    await communicate.save(filename)

def build_full_video():
    clips = []
    temp_files = []

    print("🚀 [1/3] 开始生成全新多场景短视频 (主题: 免打开 Keil 与 CubeMX 的全流程开发)...")
    for idx, scene in enumerate(SCENES):
        audio_file = f"temp_voice_{idx}.mp3"
        temp_files.append(audio_file)
        
        print(f"   -> [场景 {idx+1}/{len(SCENES)}] 正在合成语音: {scene['title']}")
        asyncio.run(generate_voice(scene["voice"], audio_file))
        audio_clip = AudioFileClip(audio_file)
        duration = audio_clip.duration

        # 针对当前场景渲染动态帧
        def make_frame(t, current_scene=scene, dur=duration):
            return render_frame_by_scene(t, current_scene, dur)

        vclip = VideoClip(make_frame, duration=duration).set_audio(audio_clip)
        clips.append(vclip)

    print("🎬 [2/3] 拼接 5 大动效场景与音轨...")
    final_video = concatenate_videoclips(clips, method="compose")

    print("⚡ [3/3] 正在导出 1080x1920 高清抖音短视频 (douyin_stm32_video.mp4)...")
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

    print("✅ 全新短视频生成完毕！已生成在: douyin_stm32_video.mp4")

if __name__ == "__main__":
    build_full_video()
