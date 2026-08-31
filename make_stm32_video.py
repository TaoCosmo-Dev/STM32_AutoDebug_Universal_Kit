import os
import sys
import asyncio
import textwrap
import edge_tts
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# ==========================================
# 1. 抖音短视频文案配置 (STM32 AutoDebug 专属爆款脚本)
# ==========================================
SCENES = [
    {
        "tag": "嵌入式痛点",
        "title": "还在通宵查 HardFault 吗？",
        "desc": "写单片机代码最怕什么？\n时钟树配置繁琐、引脚冲突难查、\n寄存器死锁导致单片机直接卡死！",
        "voice": "写单片机代码还在通宵查哈德福特吗？最头疼的时钟配错、引脚复用冲突、寄存器死锁，现在全部有解了！"
    },
    {
        "tag": "解决方案",
        "title": "AI 硬件在环固件架构师",
        "desc": "从模糊需求出发，五大硬件决策深度访谈！\n自动生成小白防呆接线图与避坑指南，\n你只需照图插线，剩下的全部交给 AI！",
        "voice": "隆重推荐这个开源神器：STM32 硬件在环自愈开发套件！AI 自动深度访谈，排查引脚冲突，生成小白防呆接线图，你只需照图插线。"
    },
    {
        "tag": "硬核特性",
        "title": "Keil 0 Error 闭环自愈",
        "desc": "固件代码自动编写 + 循环纠错自愈，\nJTAG/SWD 探针免交互在线烧录，\n自动嗅探串口波特率与 CPU 寄存器遥测！",
        "voice": "更绝的是，它全程接管代码编写，自动调用 Keil 进行零报错编译自愈，配合探针免交互在线烧录，自动嗅探串口与寄存器！"
    },
    {
        "tag": "开源获取",
        "title": "GitHub 立即体验",
        "desc": "项目地址: TaoCosmo-Dev / STM32_AutoDebug_Universal_Kit\n赶紧点赞收藏，前往 GitHub 体验吧！",
        "voice": "项目现已完全开源，GitHub 搜索 TaoCosmo-Dev，赶紧点赞收藏加关注，去 Star 体验吧！"
    }
]

# ==========================================
# 2. 绘制 1080x1920 科技风卡片
# ==========================================
def get_chinese_font(size):
    font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "C:\\Windows\\Fonts\\msyh.ttc",
        "C:\\Windows\\Fonts\\simhei.ttf",
        "msyh.ttc",
        "simhei.ttf"
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()

def draw_scene_frame(scene, width=1080, height=1920):
    img = Image.new("RGB", (width, height), color=(11, 15, 25))
    draw = ImageDraw.Draw(img)

    # 绘制科技感背景
    for y in range(height):
        ratio = y / height
        r = int(10 + 12 * ratio)
        g = int(14 + 20 * ratio)
        b = int(24 + 40 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    font_tag = get_chinese_font(38)
    font_title = get_chinese_font(52)
    font_desc = get_chinese_font(38)
    font_author = get_chinese_font(32)

    # 顶部标签栏
    draw.rectangle([(80, 180), (1000, 270)], fill=(30, 41, 59), outline=(56, 189, 248), width=3)
    draw.text((120, 205), f"★ {scene['tag']} | 极客开源", fill=(56, 189, 248), font=font_tag)

    # 主体大卡片
    draw.rectangle([(80, 340), (1000, 1420)], fill=(15, 23, 42), outline=(71, 85, 105), width=2)

    # 卡片内部：项目名称
    draw.text((130, 410), "STM32 AutoDebug Copilot Kit", fill=(148, 163, 184), font=font_author)
    
    # 卡片内部：核心标题
    draw.text((130, 490), scene["title"], fill=(251, 191, 36), font=font_title)

    # 分割线
    draw.line([(130, 590), (950, 590)], fill=(51, 65, 85), width=2)

    # 核心介绍内容（多行）
    y_text = 640
    for line in scene["desc"].split("\n"):
        draw.text((130, y_text), line, fill=(241, 245, 249), font=font_desc)
        y_text += 70

    # 底部作者与仓库水印
    draw.rectangle([(80, 1580), (1000, 1700)], fill=(30, 41, 59), outline=(56, 189, 248), width=2)
    draw.text((120, 1620), "GitHub 搜索: TaoCosmo-Dev", fill=(203, 213, 225), font=font_tag)

    return np.array(img)

# ==========================================
# 3. 语音合成与视频剪辑组装
# ==========================================
async def generate_audio_for_scene(text, filename):
    communicate = edge_tts.Communicate(text, voice="zh-CN-YunxiNeural", rate="+12%")
    await communicate.save(filename)

def build_douyin_video():
    clips = []
    temp_files = []

    print("▶️ [1/3] 开始生成场景配音与视觉卡片...")
    for idx, scene in enumerate(SCENES):
        audio_file = f"temp_voice_{idx}.mp3"
        temp_files.append(audio_file)
        
        print(f"   -> 正在生成场景 {idx+1} 配音: {scene['title']}")
        asyncio.run(generate_audio_for_scene(scene["voice"], audio_file))
        audio_clip = AudioFileClip(audio_file)
        
        frame_np = draw_scene_frame(scene)
        img_clip = ImageClip(frame_np).set_duration(audio_clip.duration).set_audio(audio_clip)
        clips.append(img_clip)

    print("▶️ [2/3] 拼接场景与音轨...")
    final_video = concatenate_videoclips(clips, method="compose")

    print("▶️ [3/3] 正在导出 1080x1920 抖音短视频 (douyin_stm32_video.mp4)...")
    final_video.write_videofile(
        "douyin_stm32_video.mp4",
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=4
    )

    # 释放资源
    for clip in clips:
        clip.close()
    final_video.close()

    # 清理临时文件
    for f in temp_files:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    print("✅ 导出成功！视频保存在: douyin_stm32_video.mp4")

if __name__ == "__main__":
    build_douyin_video()
