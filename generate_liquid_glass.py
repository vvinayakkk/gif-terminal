import gifos
import os
import glob
import requests
from PIL import Image, ImageFilter, ImageDraw, ImageChops
from gifos.utils.convert_ansi_escape import ConvertAnsiEscape

# Override with high-contrast colors for blue glass background.
# Avoid cyan/blue tones — they blend with the wallpaper.
ConvertAnsiEscape.ANSI_ESCAPE_MAP_TXT_COLOR.update({
    "39": "#FFFFFF",   # default fg → pure white
    "31": "#FF3355",   # red
    "32": "#00FF88",   # neon green
    "33": "#FFE500",   # pure yellow
    "34": "#FF9500",   # orange (blue would blend)
    "35": "#FF44DD",   # magenta
    "36": "#FFFFFF",   # cyan → white (cyan blends with wallpaper)
    "37": "#FFFFFF",   # white
    "91": "#FF3355",   # bright red
    "92": "#00FF88",   # bright neon green
    "93": "#FFE500",   # bright yellow
    "94": "#FF9500",   # bright orange
    "95": "#FF44DD",   # bright magenta
    "96": "#FFE500",   # bright cyan → yellow (cyan blends)
    "97": "#FFFFFF",   # bright white
})

# ============================================
# Liquid Glass Theme — macOS-style terminal
# ============================================
#
# REQUIREMENTS:
# 1. Create a .env file in the project folder
# 2. Add: GITHUB_TOKEN=your_token_here
# 3. assets/wallpaper.jpg must be present
#
# APPROACH:
# gifos generates terminal frames with the default background (#0c0e0f).
# Before assembling the GIF, each PNG frame is post-processed:
#   - wallpaper fills the GIF canvas
#   - frosted glass (blurred wallpaper + dark overlay) covers the terminal window
#   - terminal content is composited using chroma-key (bg pixels show glass through)
#   - macOS chrome (rounded border, shadow, traffic lights) is drawn on top
# ============================================

# Auto-detected from GitHub Actions context; falls back to env var or default.
USERNAME = (
    os.environ.get("GITHUB_REPOSITORY_OWNER")
    or os.environ.get("GIT_USERNAME")
    or "dbuzatto"
)

# ---- Layout constants ----
GIF_W, GIF_H     = 740, 520   # full canvas including margin
WIN_X, WIN_Y     = 20, 25     # window top-left in canvas
WIN_W            = 700        # window width (matches gifos terminal width)
TITLE_H          = 30         # macOS title bar height
WIN_H            = TITLE_H + 450  # total window height (480)
TERMINAL_X       = WIN_X      # gifos frame is pasted here
TERMINAL_Y       = WIN_Y + TITLE_H
CORNER_RADIUS    = 10

# Default gifos background color (ANSI code 49 → #0c0e0f) — used as chroma key
BG_COLOR_HEX = "#0c0e0f"
BG_COLOR     = (12, 14, 15)


# GitHub Stats screen (and the get_total_repos/get_total_stars/get_top_languages
# helpers + gifos.utils.fetch_github_stats call that fed it) was removed
# entirely — it looked bad and added an unnecessary GitHub API round trip.


# ============================================
# Liquid Glass helpers
# ============================================

def _scale_crop(img, target_w, target_h):
    """Scale image to fill target dimensions (maintain aspect ratio, center-crop)."""
    w, h = img.size
    ratio = w / h
    target_ratio = target_w / target_h
    if ratio > target_ratio:
        new_h = target_h
        new_w = int(new_h * ratio)
    else:
        new_w = target_w
        new_h = int(new_w / ratio)
    scaled = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return scaled.crop((left, top, left + target_w, top + target_h))


def _blend_overlay(base_rgb, overlay_rgba):
    """Alpha-composite an RGBA overlay onto an RGB base."""
    result = Image.alpha_composite(base_rgb.convert("RGBA"), overlay_rgba)
    return result.convert("RGB")


def prepare_glass_layers(wallpaper_path):
    """
    Build the static base canvas and chrome overlay used for every frame.

    Returns:
        base_canvas  — RGB image (GIF_W × GIF_H): wallpaper + shadow + frosted window
        chrome       — RGBA image (GIF_W × GIF_H): window border + traffic lights
    """
    wallpaper = Image.open(wallpaper_path).convert("RGB")
    wallpaper_bg = _scale_crop(wallpaper, GIF_W, GIF_H)

    # ---- Drop shadow (rendered beneath window) ----
    shadow = Image.new("RGBA", (GIF_W, GIF_H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        [(WIN_X + 4, WIN_Y + 6), (WIN_X + WIN_W + 3, WIN_Y + WIN_H + 5)],
        radius=CORNER_RADIUS,
        fill=(0, 0, 0, 130),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))

    wallpaper_with_shadow = _blend_overlay(wallpaper_bg, shadow)

    # ---- Frosted glass — title bar ----
    # Darker tint (not pure black) so white terminal text reads clearly
    # against the blue wallpaper — was a light-white tint, too washed out.
    title_region = wallpaper_bg.crop((WIN_X, WIN_Y, WIN_X + WIN_W, WIN_Y + TITLE_H))
    frosted_title = title_region.filter(ImageFilter.GaussianBlur(radius=5))
    title_overlay = Image.new("RGBA", frosted_title.size, (10, 12, 18, 150))
    frosted_title = _blend_overlay(frosted_title, title_overlay)

    # ---- Frosted glass — content area ----
    content_region = wallpaper_bg.crop(
        (TERMINAL_X, TERMINAL_Y, TERMINAL_X + WIN_W, TERMINAL_Y + 450)
    )
    frosted_content = content_region.filter(ImageFilter.GaussianBlur(radius=4))
    content_overlay = Image.new("RGBA", frosted_content.size, (8, 10, 16, 165))
    frosted_content = _blend_overlay(frosted_content, content_overlay)

    # ---- Assemble frosted window (with rounded corners) ----
    window_img = Image.new("RGB", (WIN_W, WIN_H))
    window_img.paste(frosted_title, (0, 0))
    window_img.paste(frosted_content, (0, TITLE_H))

    window_mask = Image.new("L", (WIN_W, WIN_H), 0)
    ImageDraw.Draw(window_mask).rounded_rectangle(
        [(0, 0), (WIN_W - 1, WIN_H - 1)], radius=CORNER_RADIUS, fill=255
    )

    # ---- Composite: wallpaper_with_shadow + frosted window ----
    base_canvas = wallpaper_with_shadow.copy()
    base_canvas.paste(window_img, (WIN_X, WIN_Y), window_mask)

    # ---- Chrome overlay (RGBA): border + title separator + traffic lights ----
    chrome = Image.new("RGBA", (GIF_W, GIF_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(chrome)

    # Window border
    draw.rounded_rectangle(
        [(WIN_X, WIN_Y), (WIN_X + WIN_W - 1, WIN_Y + WIN_H - 1)],
        radius=CORNER_RADIUS,
        outline=(255, 255, 255, 55),
        width=1,
    )

    # Title bar bottom separator
    draw.line(
        [
            (WIN_X + CORNER_RADIUS, WIN_Y + TITLE_H),
            (WIN_X + WIN_W - CORNER_RADIUS, WIN_Y + TITLE_H),
        ],
        fill=(255, 255, 255, 35),
        width=1,
    )

    # Traffic lights
    tl_y = WIN_Y + TITLE_H // 2
    traffic_lights = [
        ("#FF5F57", "#E0443E"),  # red
        ("#FFBD2E", "#DFA223"),  # yellow
        ("#28C840", "#1DAD2B"),  # green
    ]
    tl_r = 6
    for i, (fill, outline) in enumerate(traffic_lights):
        cx = WIN_X + 15 + i * 20 + tl_r
        draw.ellipse(
            [(cx - tl_r, tl_y - tl_r), (cx + tl_r, tl_y + tl_r)],
            fill=fill,
            outline=outline,
        )

    return base_canvas, chrome


def chroma_mask(terminal_frame):
    """
    Returns an 'L' mask:  255 = terminal pixel (keep)  /  0 = background (show glass).
    Any pixel exactly equal to BG_COLOR becomes 0 (transparent).
    """
    bg_ref = Image.new("RGB", terminal_frame.size, BG_COLOR)
    diff   = ImageChops.difference(terminal_frame, bg_ref)
    r, g, b = diff.split()
    # 255 if ANY channel differs from BG_COLOR
    mask = ImageChops.lighter(ImageChops.lighter(r, g), b)
    return mask.point(lambda p: 255 if p > 0 else 0)


def post_process_frames(base_canvas, chrome, frames_dir="./frames"):
    """Composite the liquid glass effect onto every PNG frame gifos generated."""
    frame_files = sorted(
        glob.glob(f"{frames_dir}/frame_*.png"),
        key=lambda x: int(os.path.splitext(os.path.basename(x))[0].split("_")[1]),
    )
    print(f"INFO: Post-processing {len(frame_files)} frames with liquid glass effect...")
    for frame_path in frame_files:
        terminal_frame = Image.open(frame_path).convert("RGB")
        canvas = base_canvas.copy()

        # Paste only non-background pixels (chroma key)
        mask = chroma_mask(terminal_frame)
        canvas.paste(terminal_frame, (TERMINAL_X, TERMINAL_Y), mask)

        # Apply chrome overlay (border + traffic lights)
        canvas = Image.alpha_composite(canvas.convert("RGBA"), chrome).convert("RGB")

        canvas.save(frame_path, "PNG")

    print(f"INFO: Liquid glass post-processing complete ({len(frame_files)} frames).")


# ============================================
# Terminal — content generation (gifos)
# ============================================

t = gifos.Terminal(width=WIN_W, height=450, xpad=10, ypad=10)
t.set_prompt(f"\x1b[91m{USERNAME}\x1b[0m@\x1b[93mgithub\x1b[0m ~> ")

# gifos_settings.toml sets fps=15. "Lightning fast" pacing: hold just long
# enough to read one line, then move — no idle padding once typing/text has
# landed. GitHub Stats screen removed entirely (not just hidden) per feedback
# that it looked bad.
HACKATHON_HOLD = 18   # ~1.2s at 15fps
PUB_HOLD = 45         # ~3s — 5 items, still worth a beat longer than a hackathon line
TICK = 1              # frame gap between successive gen_text lines on one screen

# -- ASCII boot banner --
t.gen_text("+--------------------------------------+", row_num=1)
t.gen_text("|          VINAYAK BHATIA               |", row_num=2)
t.gen_text("|  SDE @ Media.net - AI/ML Engineer     |", row_num=3)
t.gen_text("+--------------------------------------+", row_num=4)
t.clone_frame(15)
t.clear_frame()

# -- Hackathons --
t.gen_prompt(row_num=1)
t.gen_typing_text("cat hackathons.txt", row_num=1, contin=True, speed=1)
t.clone_frame(TICK)

t.gen_text("", row_num=2)
t.gen_text("\x1b[96m=== 17 Hackathons Won ===\x1b[0m", row_num=3)
t.clone_frame(TICK)

# One entry: (name, venue/level, result). Exactly 17 — matches the "17x Hackathon
# Winner" headline. Each gets its own full screen + a 10s hold (HOLD_FRAMES).
hackathons = [
    ("AiVolution Hackathon 2025", "Media.net - Corporate", "1st Place"),
    ("Google Cloud Agentic AI Day", "Hack2skill - Open", "Winner"),
    ("Airavat AI Hackathon 2025", "IEEE CS, SPIT - Institutional", "1st Place"),
    ("Code Crafters 2.0", "Saraswati College of Engg", "1st Place"),
    ("Hackanova 5.0 - AIML Domain", "Thakur College - National", "1st Place"),
    ("SPIT Hackathon 2025 - AIML", "CSI SPIT - Institutional", "1st Place"),
    ("Genathon 2.0", "IIIT Nagpur - National", "1st Place"),
    ("D3CODE Hackathon 2025", "UST Global - Corporate", "Runner-Up"),
    ("LogiTHON AI Hackathon", "IIT Bombay / IEOR", "Runner-Up"),
    ("AI-Quest", "IIT Bombay Techfest '24", "2nd Place"),
    ("Classifi", "IIT Bombay Techfest '24", "2nd Place"),
    ("Datathon 2025 - GenAI Track", "KJ Somaiya", "Runner-Up"),
    ("Odoo x Gujarat Vidyapeeth", "National Hackathon 2025", "2nd Runner-Up"),
    ("Wall Street Analytics Challenge", "BITS Pilani Hyderabad", "2nd Runner-Up"),
    ("ML Fiesta", "IIIT Bangalore", "2nd Runner-Up"),
    ("Technovate 2.0", "Rotaract, SPIT", "5th Place"),
    ("Smart India Hackathon 2024", "IIT Gandhinagar - National", "Top 5 Finalist"),
]
assert len(hackathons) == 17

t.clone_frame(HACKATHON_HOLD)  # hold the "17 Hackathons Won" title screen too
t.clear_frame()

for i, (name, venue, result) in enumerate(hackathons, start=1):
    t.gen_text(f"\x1b[96m[{i:>2}/17]\x1b[0m", row_num=1)
    t.gen_text(f"\x1b[97m{name}\x1b[0m", row_num=2)
    t.gen_text(f"\x1b[94m{venue}\x1b[0m", row_num=3)
    t.gen_text(f"\x1b[93m{result}\x1b[0m", row_num=4)
    t.clone_frame(HACKATHON_HOLD)
    if i < len(hackathons):
        t.clear_frame()

t.clear_frame()

# -- Clear + Publications --
pub_prompt_row = 1
t.gen_prompt(row_num=pub_prompt_row)
t.gen_typing_text("clear", row_num=pub_prompt_row, contin=True, speed=1)
t.clone_frame(TICK)
t.clear_frame()

t.gen_prompt(row_num=1)
t.gen_typing_text("cat publications.txt", row_num=1, contin=True, speed=1)
t.clone_frame(TICK)

t.gen_text("", row_num=2)
t.gen_text("\x1b[96m=== Publications (5) ===\x1b[0m", row_num=3)
t.clone_frame(HACKATHON_HOLD)
t.clear_frame()

# Each entry: (title lines, venue, status). One screen per publication, 10s hold.
publications = [
    (
        ["Hybrid Quantum-Classical Framework for", "Hyperspectral Image Classification:",
         "QAOA-Optimised Band Selection w/ 3D-CNNs"],
        "Intl. Journal of Remote Sensing (Taylor & Francis) - Q1",
        "Accepted - Sep 2026",
    ),
    (
        ["DualScope-LSTM: Adaptive Dual-Branch", "Modeling for Cloud Resource Forecasting"],
        "IEEE ISCMI 2025 + T&F Special Issue - Q1",
        "Published (IEEE) / Accepted (Q1 Journal)",
    ),
    (
        ["Saves: A Spatio-Temporal Attention-Based", "Approach for Video Surveillance"],
        "IEEE Intl. Conf. on Image Processing Workshops (ICIPW) 2025",
        "Published",
    ),
    (
        ["VehicleVision Transatron for Fine-Grained", "Vehicle Classification"],
        "TIPCE Conference, IIT Roorkee 2025",
        "Published",
    ),
    (
        ["CropNet"],
        "NeurIPS 2026",
        "Submitted",
    ),
]
assert len(publications) == 5

for i, (title_lines, venue, status) in enumerate(publications, start=1):
    t.gen_text(f"\x1b[96m[{i}/5]\x1b[0m", row_num=1)
    row = 2
    for line in title_lines:
        t.gen_text(f"\x1b[97m{line}\x1b[0m", row_num=row)
        row += 1
    t.gen_text(f"\x1b[94m{venue}\x1b[0m", row_num=row)
    t.gen_text(f"\x1b[93m{status}\x1b[0m", row_num=row + 1)
    t.clone_frame(PUB_HOLD)
    if i < len(publications):
        t.clear_frame()

t.clear_frame()

# -- Clear + Tech Stack --
stack_prompt_row = 1
t.gen_prompt(row_num=stack_prompt_row)
t.gen_typing_text("clear", row_num=stack_prompt_row, contin=True, speed=1)
t.clone_frame(TICK)
t.clear_frame()

t.gen_prompt(row_num=1)
t.gen_typing_text("cat stack.txt", row_num=1, contin=True, speed=1)
t.clone_frame(TICK)

t.gen_text("", row_num=2)
t.gen_text("\x1b[96m=== Tech Stack ===\x1b[0m", row_num=3)
t.clone_frame(TICK)

skills = [
    ("\x1b[94mBackend:\x1b[0m      ", "Spring Boot, FastAPI, Django, Node.js"),
    ("\x1b[94mCloud:\x1b[0m        ", "AWS, GCP, Azure"),
    ("\x1b[94mContainers:\x1b[0m   ", "Docker, Kubernetes, Helm"),
    ("\x1b[94mIaC / GitOps:\x1b[0m ", "Terraform, FluxCD, ArgoCD"),
    ("\x1b[94mCI/CD:\x1b[0m        ", "Jenkins, GitHub Actions, GitLab CI"),
    ("\x1b[94mMessaging:\x1b[0m    ", "Kafka, RabbitMQ"),
    ("\x1b[94mObservability:\x1b[0m", "Grafana, Prometheus, ELK"),
    ("\x1b[94mDatabases:\x1b[0m    ", "PostgreSQL, MongoDB, Redis"),
    ("\x1b[94mLanguages:\x1b[0m    ", "Java, Python, Go"),
]

for i, (label, value) in enumerate(skills):
    t.gen_text(f"{label}{value}", row_num=4 + i)
    t.clone_frame(TICK)

t.clone_frame(TICK)
t.gen_text("\x1b[96m==================\x1b[0m", row_num=4 + len(skills))
t.clone_frame(HACKATHON_HOLD)

# -- Final message --
final_row = 5 + len(skills)
t.gen_prompt(row_num=final_row)
t.gen_typing_text(
    "echo 'Thanks for visiting my profile!'", row_num=final_row, contin=True, speed=1
)
t.clone_frame(TICK)
t.gen_text("\x1b[92mThanks for visiting my profile!\x1b[0m", row_num=final_row + 1)
t.clone_frame(20)

# ============================================
# Post-process frames → Liquid Glass effect
# ============================================

base_canvas, chrome = prepare_glass_layers("assets/macos_wallpaper.jpg")
post_process_frames(base_canvas, chrome)

# ============================================
# Generate GIF
# ============================================

t.gen_gif()

print("\n GIF generated: output.gif")
print("\nTo use in your README.md:")
print("![Terminal GIF](./output.gif)")
