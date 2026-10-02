# -*- coding: utf-8 -*-
"""CogVideoX-3 视频生成脚本（智谱开放平台 API）

双击 生成视频.bat 使用，或命令行：
    uv run python generate_video.py --prompt "画面描述"
    uv run python generate_video.py --prompt "镜头推进" --image 图片.jpg
"""
import argparse
import base64
import os
import sys
import time
from pathlib import Path

from zhipuai import ZhipuAI

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "outputs"

MODELS = {
    "1": ("cogvideox-3", "标准：1080p / 30帧 / 5秒"),
    "2": ("cogvideox-3", "高清：4K / 30帧 / 5秒"),
    "3": ("cogvideox-3", "流畅：1080p / 60帧 / 5秒"),
    "4": ("cogvideox-flash", "免费：cogvideox-flash / 5秒（不扣费）"),
}


def load_api_key() -> str:
    key = os.environ.get("ZHIPUAI_API_KEY", "").strip()
    if key:
        return key
    key_file = BASE_DIR / "key.txt"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    sys.exit("未找到 API Key：请设置环境变量 ZHIPUAI_API_KEY，或在脚本目录创建 key.txt 写入 key")


def to_image_param(image: str) -> str:
    """URL 直接返回；本地文件转成 Base64（API 同时支持两种）"""
    if image.lower().startswith(("http://", "https://")):
        return image
    path = Path(image.strip('"'))
    if not path.exists():
        sys.exit(f"图片文件不存在: {image}")
    return base64.b64encode(path.read_bytes()).decode()


def ask(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
    except EOFError:
        val = ""
    return val or default


def interactive_fill(args: argparse.Namespace) -> None:
    print("=== CogVideoX-3 视频生成 ===")
    print("生成方式：")
    for k, (_, desc) in MODELS.items():
        extra = {
            "2": "（3840x2160）", "3": "（60帧，smoothness）",
        }.get(k, "")
        print(f"  {k}) {desc}{extra}")
    mode = ask("第1问/共5问，选择生成方式 [回车=1]: ", "1")
    if mode not in MODELS:
        mode = "1"
    model, _ = MODELS[mode]
    if args.model is None:
        args.model = model
    if mode == "2" and not args.size:
        args.size = "3840x2160"
    if mode == "3":
        args.fps = args.fps or 60
        args.quality = "smoothness"

    if not args.duration:
        d = ask("第2问/共5问，视频时长秒数（只支持 5 或 10）[回车=5]: ")
        if d.isdigit():
            args.duration = int(d)

    if args.clips is None:
        c = ask("第3问/共5问，长视频：生成几段？每段10秒自动拼接 [回车=1（单段）]: ")
        args.clips = int(c) if c.isdigit() and int(c) > 0 else 1

    if not args.prompt:
        args.prompt = ask("第4问/共5问，画面描述（提示词填这里）: ")

    if not args.image:
        img = ask("第5问/共5问，首帧图片：拖图片进本窗口，或输入网址 [回车=不用图片]: ")
        if img:
            looks_like_path = img.lower().startswith(("http://", "https://")) \
                or Path(img.strip('"')).exists()
            if looks_like_path:
                args.image = img
            else:
                print(">> 这段文字不是图片路径，已自动当作画面描述使用，继续生成。")
                if len(img) > len(args.prompt or ""):
                    args.prompt = img

    if not args.prompt:
        args.prompt = "让画面自然地动起来"


def poll_result(client: ZhipuAI, task_id: str, timeout_min: int = 20) -> dict:
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        result = client.videos.retrieve_videos_result(id=task_id)
        status = result.task_status
        if status == "SUCCESS":
            return result
        if status == "FAIL":
            raise RuntimeError(f"生成失败: {result}")
        print(f"  状态: {status}，继续等待...")
        time.sleep(10)
    raise TimeoutError("超过等待时限，可稍后用任务 id 手动查询")


def generate_one(client: ZhipuAI, kwargs: dict) -> Path:
    print(f"\n提交任务: {kwargs['prompt'][:50]}...")
    resp = client.videos.generations(**kwargs)
    print(f"任务 ID: {resp.id}")
    result = poll_result(client, resp.id)
    OUTPUT_DIR.mkdir(exist_ok=True)
    dest = OUTPUT_DIR / f"{resp.id}_0.mp4"
    print(f"下载视频 -> {dest}")
    download(result.video_result[0].url, dest)
    return dest


def extract_last_frame(video: Path, png: Path) -> None:
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.2", "-i", str(video),
         "-frames:v", "1", "-q:v", "2", str(png)],
        check=True, capture_output=True,
    )


def stitch_clips(clips: list, dest: Path) -> None:
    import subprocess
    listfile = dest.with_suffix(".txt")
    listfile.write_text("\n".join(f"file '{c}'" for c in clips), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(dest)],
        check=True, capture_output=True,
    )
    listfile.unlink()


def download(url: str, dest: Path) -> None:
    import httpx
    with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def main() -> None:
    parser = argparse.ArgumentParser(description="CogVideoX-3 视频生成")
    parser.add_argument("--prompt", default=None, help="视频描述（图生视频时描述画面运动方式）")
    parser.add_argument("--image", default=None, help="首帧图片：本地路径或 URL")
    parser.add_argument("--model", default=None, help="模型名，默认 cogvideox-3")
    parser.add_argument("--size", default=None, help='分辨率，如 "1920x1080"、"3840x2160"')
    parser.add_argument("--duration", type=int, default=None, help="时长（秒）")
    parser.add_argument("--clips", type=int, default=None, help="长视频分段数，每段10秒自动拼接")
    parser.add_argument("--fps", type=int, default=None, help="帧率 30 或 60")
    parser.add_argument("--quality", default="quality", choices=["quality", "smoothness"],
                        help="quality=清晰优先, smoothness=流畅优先")
    parser.add_argument("--no-audio", action="store_true", help="不生成音频")
    args = parser.parse_args()

    interactive_fill(args)

    client = ZhipuAI(api_key=load_api_key())

    kwargs = dict(
        model=args.model,
        prompt=args.prompt,
        quality=args.quality,
        with_audio=not args.no_audio,
    )
    if args.image:
        kwargs["image_url"] = to_image_param(args.image)
    if args.size:
        kwargs["size"] = args.size
    if args.duration:
        if args.duration not in (5, 10):
            fixed = 5 if abs(args.duration - 5) <= abs(args.duration - 10) else 10
            print(f">> 时长 {args.duration} 秒暂不支持（只支持 5 或 10 秒），已自动改为 {fixed} 秒")
            args.duration = fixed

    n_clips = args.clips or 1
    if n_clips > 1:
        args.duration = 10
        if args.model != "cogvideox-flash":
            est = round(n_clips * 10 * 0.17, 1)
            ok = input(f">> 长视频共 {n_clips} 段 x 10 秒，预计扣费约 {est} 元，继续？(回车=继续, n=取消): ").strip().lower()
            if ok == "n":
                sys.exit("已取消")

    kwargs = dict(
        model=args.model,
        prompt=args.prompt,
        quality=args.quality,
        with_audio=not args.no_audio,
    )
    if args.image:
        kwargs["image_url"] = to_image_param(args.image)
    if args.size:
        kwargs["size"] = args.size
    if args.duration:
        kwargs["duration"] = args.duration
    if args.fps:
        kwargs["fps"] = args.fps

    OUTPUT_DIR.mkdir(exist_ok=True)

    if n_clips == 1:
        final = generate_one(client, kwargs)
        print(f"\n完成: {final}")
        return

    # 长视频模式：逐段生成，用上一段最后一帧接续，最后无损拼接
    base_prompt = kwargs["prompt"]
    image_param = kwargs.get("image_url")
    kwargs["with_audio"] = False  # 多段拼接统一不带音频，保证音画结构一致
    clips = []
    for i in range(1, n_clips + 1):
        seg = dict(kwargs)
        seg["duration"] = 10
        if i > 1:
            seg["prompt"] = f"延续上一段画面的运动、风格与镜头，自然继续：{base_prompt}"
        if image_param:
            seg["image_url"] = image_param
        print(f"\n===== 第 {i}/{n_clips} 段 =====")
        clip = generate_one(client, seg)
        clips.append(clip)
        if i < n_clips:
            frame = OUTPUT_DIR / f"lastframe_seg{i}.png"
            extract_last_frame(clip, frame)
            image_param = to_image_param(str(frame))

    final = OUTPUT_DIR / f"long_{n_clips}x10s_{int(time.time())}.mp4"
    stitch_clips(clips, final)
    print(f"\n长视频完成: {final}（共 {n_clips} 段）")


if __name__ == "__main__":
    import traceback

    class Tee:
        """同时输出到屏幕和日志文件，崩溃后可回查原因"""
        def __init__(self):
            self.file = open(BASE_DIR / "run.log", "a", encoding="utf-8")
        def write(self, s):
            try:
                sys.__stdout__.write(s)
            except Exception:
                pass
            self.file.write(s)
            self.file.flush()
        def flush(self):
            try:
                sys.__stdout__.flush()
            except Exception:
                pass

    try:
        sys.stdout = Tee()
        sys.stderr = sys.stdout
        main()
    except SystemExit as e:
        if e.code and e.code != 0:
            print(f"已退出: {e.code}")
            time.sleep(3)
    except Exception:
        print("\n出错了！详细原因已保存到 run.log，把这段信息发给助手即可定位问题：")
        traceback.print_exc()
        time.sleep(10)
