"""video.py - turn a recorded rehearsal into an MP4: the game's screen and the DUO's side by side.

    VDUO_RECORD=FRAMES python3 trade.py ...          (any rehearsal: vduo.py saves both screens
                                                       every VDUO_RECORD_STEP frames, default 2)
    python3 video.py FRAMES OUT.mp4 --title "Trading with Pokemon Ruby" [--speed 1] [--scale 3]

Needs ffmpeg. Frames 2 apart play at 30 a second, so --speed 1 is real time.
"""
import argparse, glob, os, shutil, subprocess, sys

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]


def esc(t):
    return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("frames")
    ap.add_argument("out")
    ap.add_argument("--title", default="")
    ap.add_argument("--left", default="The game (mGBA)")
    ap.add_argument("--right", default="Action Replay MAX DUO, Reckless firmware (emulated)")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--scale", type=int, default=3)
    ap.add_argument("--step", type=int, default=int(os.environ.get("VDUO_RECORD_STEP", "2")))
    a = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg isn't installed")
    n = len(glob.glob(os.path.join(a.frames, "*_partner.png")))
    if not n:
        sys.exit("no frames there")
    fps = 60.0 / a.step * a.speed
    font = next((f for f in FONTS if os.path.exists(f)), None)
    w, h, bar = 240 * a.scale, 160 * a.scale, 28 * a.scale // 3
    text = ""
    if font:
        big, small = 22 * a.scale // 3, 15 * a.scale // 3
        text = (f",pad={2 * w}:{h + 2 * bar}:0:{bar}:0x101418"
                f",drawtext=fontfile={font}:text='{esc(a.title)}':fontcolor=white:fontsize={big}:x=(w-tw)/2:y=({bar}-th)/2"
                f",drawtext=fontfile={font}:text='{esc(a.left)}':fontcolor=0xB0B8C0:fontsize={small}:x=({w}-tw)/2:y={h + bar}+({bar}-th)/2"
                f",drawtext=fontfile={font}:text='{esc(a.right)}':fontcolor=0xB0B8C0:fontsize={small}:x={w}+({w}-tw)/2:y={h + bar}+({bar}-th)/2")
        if a.speed != 1:
            text += (f",drawtext=fontfile={font}:text='{a.speed:g}x':fontcolor=0xB0B8C0:fontsize={small}"
                     f":x=w-tw-{bar // 2}:y=({bar}-th)/2")
    filt = (f"[0:v]scale={w}:{h}:flags=neighbor[l];[1:v]scale={w}:{h}:flags=neighbor[r];"
            f"[l][r]hstack=inputs=2{text},format=yuv420p[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-framerate", f"{fps:g}", "-i", os.path.join(a.frames, "%06d_partner.png"),
           "-framerate", f"{fps:g}", "-i", os.path.join(a.frames, "%06d_duo.png"),
           "-filter_complex", filt, "-map", "[v]", "-r", "30",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True)
    print(f"{a.out}: {n} frames, {n / fps:.0f} s")


if __name__ == "__main__":
    main()
