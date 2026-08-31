import os
import asyncio
import edge_tts
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# ==========================================
# 1. 抖音短视频文案配置 (STM32 AutoDebug 专属爆款脚本)
# ==========================================
SCENES = [
    {
        "tag": "🚨 嵌入式痛点",
        "title": "还在通宵查 HardFault 吗？",
        "desc": "写单片机代码最怕什么？时钟配错、引脚冲突、寄存器死锁！",
        "voice": "写单片机代码还在通宵查哈德福特吗？最头疼的时钟配错、引脚复用冲突、寄存器死锁，现在全部有解了！"
    },
    {
        "tag": "💡 解决方案",
        "title": "AI 硬件在环固件架构师",
        "desc": "从需求出发，5大决策自动访谈，生成小白防呆接线图与避坑指南。",
        "voice": "隆重推荐这个开源神器：STM32 硬件在环自愈开发套件！AI 自动深度访谈，排查引脚冲突，生成小白防呆接线图，你只需照图插线。"
    },
    {
        "tag": "⚡ 硬核特性",
        "title": "Keil 0 Error 闭环自愈",
        "desc": "代码自动生成 + 循环纠错 + JTAG/SWD 探针在线免死锁烧录与寄存器遥测！",
        "voice": "更绝的是，它全程接管代码编写，自动调用 Keil 进行零报错编译自愈，配合探针免交互在线烧录，自动嗅探串口与寄存器！"
    },
    {
        "tag": "🌟 开源获取",
        "title": "GitHub 立即体验",
        "desc": "搜索 TaoCosmo-Dev / STM32_AutoDebug_Universal_Kit",
        "voice": "项目现已完全开源，GitHub 搜索 TaoCosmo-Dev，赶紧点赞收藏加关注，去 Star 体验吧！"
    }
]

# ==========================================
# 2. 绘制 1080x1920 科技风卡片 (纯 Pillow 渲染，免 ImageMagick 依赖)
# ==========================================
def draw_scene_frame(scene, width=1080, height=1920):
    img = Image.new("RGB", (width, height), color=(11, 15, 25))
    draw = ImageDraw.Draw(img)

    # 绘制科技感渐变装饰背景
    for y in range(height):
        ratio = y / height
        r = int(11 + 15 * ratio)
        g = int(15 + 25 * ratio)
        b = int(25 + 45 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 顶部装饰栏与 Header
    draw.rectangle([(80, 200), (1000, 290)], fill=(30, 41, 59), outline=(56, 189, 248), width=3)
    
    # 兼容 Linux (GitHub Actions) 与 Windows 中文字体
    font_candidates = [
        "msyh.ttc",
        "simhei.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "DejaVuSans.ttf"
    ]
    
    selected_font = None
    for fpath in font_candidates:
        if os.path.exists(fpath):
            selected_font = fpath
            break
        try:
            # 尝试由 PIL 查找系统名称
            ImageFont.truetype(fpath, 20)
            selected_font = fpath
            break
        except:
            continue

    if selected_font:
        font_tag = ImageFont.truetype(selected_font, 38)
        font_title = ImageFont.truetype(selected_font, 56)
        font_desc = ImageFont.truetype(selected_font, 40)
        font_author = ImageFont.truetype(selected_font, 34)
    else:
        font_tag = font_title = font_desc = font_author = ImageFont.load_default()

    # 绘制 Header Tag
    draw.text((120, 220), f"🚀 {scene['tag']} | 极客开源", fill=(56, 189, 248), font=font_tag)

    # 绘制大卡片背景
    draw.rounded_rectangle([(80, 360), (1000, 1400)], radius=30, fill=(15, 23, 42), outline=(71, 85, 105), width=2)

    # 卡片内部：项目名称
    draw.text((130, 430), "STM32 AutoDebug Kit", fill=(148, 163, 184), font=font_author)
    
    # 卡片内部：核心标题
    draw.text((130, 520), scene["title"], fill=(251, 191, 36), font=font_title)

    # 分割线
    draw.line([(130, 640), (950, 640)], fill=(51, 65, 85), width=2)

    # 核心介绍内容
    draw.text((130, 700), scene["desc"], fill=(248, 250, 252), font=font_desc)

    # 底部作者与仓库水印
    draw.rectangle([(80, 1600), (1000, 1720)], fill=(30, 41, 59))
    draw.text((120, 1635), "👨‍💻 GitHub: TaoCosmo-Dev", fill=(203, 213, 225), font=font_author)

    return np.array(img)

# ==========================================
# 3. 语音合成与视频剪辑组装
# ==========================================
async def generate_audio_for_scene(text, filename):
    communicate = edge_tts.Communicate(text, voice="zh-CN-YunxiNeural", rate="+15%")
    await communicate.save(filename)

def build_douyin_video():
    clips = []
    temp_files = []

    print("▶️ [1/3] 开始生成场景配音与视觉卡片...")
    for idx, scene in enumerate(SCENES):
        audio_file = f"temp_voice_{idx}.mp3"
        temp_files.append(audio_file)
        
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

    # 清理临时文件
    for f in temp_files:
        if os.path.exists(f):
            os.remove(f)

    print("✅ 导出成功！视频保存在: douyin_stm32_video.mp4")

if __name__ == "__main__":
    build_douyin_video()
