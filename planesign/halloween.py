import math
import random
import time
from pathlib import Path

import shared_config
from modes import DisplayMode, planesign_mode_handler
from PIL import Image, ImageChops, ImageDraw, ImageFilter


WIDTH = 128
HEIGHT = 32
PUMPKIN_COLORS = ((184, 59, 12), (205, 76, 9), (165, 48, 18), (219, 91, 12), (183, 96, 42), (199, 80, 24), (172, 64, 16), (188, 106, 18))
PUMPKIN_WIDTH_RANGE = (13, 29)
MIN_DRAWABLE_EYE_PIXELS = 3
FACE_ASSET_DIR = Path(shared_config.icons_dir) / "halloween"
IMAGE_EXTENSIONS = Image.registered_extensions()
FACE_ASSETS = {
    feature: tuple(
        path.name
        for path in sorted((FACE_ASSET_DIR / feature).iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    for feature in ("eyes", "mouth", "nose")
}
# These intervals control how quickly each candle changes its flicker and emits sparks.
FLAME_CHANGE_INTERVAL = (0.08, 0.18)
FLAME_SPARK_INTERVAL = (0.45, 1.2)


def load_face_assets():
    assets = {}
    for feature, filenames in FACE_ASSETS.items():
        assets[feature] = {}
        for filename in filenames:
            with Image.open(FACE_ASSET_DIR / feature / filename) as image:
                assets[feature][filename] = image.convert("RGBA")
    return assets


def draw_background():
    image = Image.new("RGB", (WIDTH, HEIGHT), (2, 3, 12))
    draw = ImageDraw.Draw(image)

    stars = random.Random(51031)
    for _ in range(23):
        x = stars.randrange(WIDTH)
        y = stars.randrange(2, 18)
        color = stars.choice(((20, 25, 39), (27, 30, 43), (34, 31, 37)))
        draw.point((x, y), fill=color)

    # Crooked branches and a low, uneven horizon keep the scene silhouetted.
    for x, direction in ((0, 1), (127, -1)):
        root = x + direction * 7
        draw.line((root, 30, root, 11), fill=(13, 16, 27), width=2)
        draw.line((root, 18, root + direction * 8, 12), fill=(13, 16, 27))
        draw.line((root + direction * 4, 15, root + direction * 3, 9), fill=(13, 16, 27))
        draw.line((root, 22, root - direction * 6, 17), fill=(13, 16, 27))
    draw.polygon(((0, 28), (16, 27), (29, 29), (45, 27), (65, 29), (86, 27), (105, 29), (128, 27), (128, 32), (0, 32)), fill=(10, 13, 22))
    return image


def create_pumpkins(assets):
    gap = 1
    min_width, max_width = PUMPKIN_WIDTH_RANGE
    widths = []
    remaining = WIDTH
    while remaining >= min_width + gap:
        width = random.randint(min_width, min(max_width, remaining - gap))
        widths.append(width)
        remaining -= width + gap

    shape_styles = ("round", "tall", "squat", "apple", "pear")
    # Add/remove names here to tune how often each small stem silhouette appears.
    stem_styles = ("stub", "curved", "forked", "twisted", "bent", "curled", "wide")
    pumpkins = []
    occupied_width = sum(widths) + gap * (len(widths) - 1)
    x = (WIDTH - occupied_width) // 2
    for body_width in widths:
        shape = random.choice(shape_styles)
        if shape == "tall":
            aspect = random.uniform(1.18, 1.42)
        elif shape == "squat":
            aspect = random.uniform(0.72, 0.88)
        elif shape == "apple":
            aspect = random.uniform(1.02, 1.26)
        elif shape == "pear":
            aspect = random.uniform(1.28, 1.5)
        else:
            aspect = random.uniform(0.98, 1.16)
        height = max(15, min(25, round(body_width * aspect)))
        bottom = random.randint(29, 31)
        mouth = random.choice(FACE_ASSETS["mouth"])
        nose = random.choice((*FACE_ASSETS["nose"], None, None))
        pumpkin = {
            "x": x,
            "y": bottom - height,
            "width": body_width,
            "bottom": bottom,
            "color": random.choice(PUMPKIN_COLORS),
            "shape": shape,
            "lobes": random.choice((5, 6, 7)),
            "stem": random.choice(stem_styles),
            "stem_height": random.randint(1, 4),
            "stem_lean": random.choice((-1, 0, 1)),
            "mouth_flip_left_right": random.choice((False, True)),
            "mouth_flip_top_bottom": random.choice((False, True)),
            "nose": nose,
            "mouth": mouth,
        }
        pumpkin["eyes"] = choose_drawable_eyes(pumpkin, assets)
        pumpkins.append(pumpkin)
        x += body_width + gap

    return sorted(pumpkins, key=lambda pumpkin: pumpkin["bottom"])


def pumpkin_outline(pumpkin):
    x, y, width = pumpkin["x"], pumpkin["y"], pumpkin["width"]
    bottom = pumpkin["bottom"]
    body_top = y + 3
    center_x = x + (width - 1) / 2
    center_y = (body_top + bottom) / 2
    radius_x = (width - 1) / 2
    radius_y = (bottom - body_top) / 2
    lobe_count = pumpkin["lobes"]
    shape = pumpkin["shape"]
    points = []
    for index in range(65):
        angle = math.tau * index / 64
        lobe = math.cos(lobe_count * angle)
        radius = 1 + 0.035 * lobe - 0.012 * math.cos(2 * lobe_count * angle)
        x_shape = radius
        y_shape = radius
        if shape == "apple":
            x_shape *= 1 - 0.18 * math.sin(angle)
        elif shape == "pear":
            vertical = math.sin(angle)
            x_shape *= 0.78 * (1 + 0.55 * vertical - 0.1 * vertical**2)
        elif shape == "tall":
            x_shape *= 1 - 0.05 * math.sin(angle)
        points.append((
            round(center_x + radius_x * x_shape * math.cos(angle)),
            round(center_y + radius_y * y_shape * math.sin(angle)),
        ))
    return points


def pumpkin_body_mask(pumpkin):
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask).polygon(pumpkin_outline(pumpkin), fill=255)
    return mask


def draw_pumpkin(image, pumpkin):
    draw = ImageDraw.Draw(image)
    x, y = pumpkin["x"], pumpkin["y"]
    width = pumpkin["width"]
    bottom = pumpkin["bottom"]
    body_top = y + 3
    body_color = pumpkin["color"]
    outline = (83, 31, 17)

    outline_points = pumpkin_outline(pumpkin)
    body_mask = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(body_mask).polygon(outline_points, fill=255)
    draw.polygon(outline_points, fill=body_color, outline=outline)

    ribs = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    rib_draw = ImageDraw.Draw(ribs)
    center_x = x + (width - 1) / 2
    center_y = (body_top + bottom) / 2
    radius_x = (width - 1) / 2
    radius_y = (bottom - body_top) / 2
    for rib in range(pumpkin["lobes"]):
        offset = (rib + 0.5) / pumpkin["lobes"] * 2 - 1
        if abs(offset) > 0.78:
            continue
        horizontal = offset * radius_x * 0.82
        curve = []
        for step in range(7):
            progress = step / 6
            py = center_y - radius_y * 0.86 + progress * radius_y * 1.72
            px = center_x + horizontal * (0.45 + 0.55 * math.sin(progress * math.pi))
            curve.append((round(px), round(py)))
        shade = (65, 23, 12, 95) if rib % 2 else (255, 151, 46, 48)
        rib_draw.line(curve, fill=shade, width=1)
    rib_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    rib_layer.alpha_composite(ribs)
    rib_layer.putalpha(ImageChops.multiply(ribs.getchannel("A"), body_mask))
    image.paste(Image.alpha_composite(image.convert("RGBA"), rib_layer).convert("RGB"))

    stem_width = max(2, width // 7)
    stem_x = x + width // 2
    stem_bottom = body_top + 2
    stem_top = max(0, y - pumpkin["stem_height"])
    stem_mid = (stem_bottom + stem_top) // 2
    lean = pumpkin["stem_lean"]
    stem = pumpkin["stem"]
    if stem == "forked":
        draw.polygon(((stem_x - 1, stem_bottom), (stem_x - 2, stem_mid), (stem_x - 1, stem_top),
                      (stem_x + 1, stem_top), (stem_x + 1, stem_mid), (stem_x + 2, stem_bottom)),
                     fill=(48, 58, 27), outline=(27, 37, 21))
        draw.line((stem_x, stem_mid, stem_x - 3, stem_top + 1), fill=(48, 58, 27), width=2)
        draw.line((stem_x, stem_mid, stem_x + 3, stem_top + 1), fill=(48, 58, 27), width=2)
    elif stem == "curved":
        curve = ((stem_x, stem_bottom), (stem_x + lean, stem_mid), (stem_x + lean * 2, stem_top))
        draw.line(curve, fill=(48, 61, 30), width=stem_width)
        draw.line(curve, fill=(27, 38, 21), width=1)
    elif stem == "curled":
        curl_side = lean or 1
        draw.line(((stem_x, stem_bottom), (stem_x, stem_mid), (stem_x + curl_side, stem_top + 1),
                   (stem_x + curl_side * 3, stem_top + 1), (stem_x + curl_side * 3, stem_top - 1)),
                  fill=(48, 61, 30), width=2)
    else:
        if stem == "stub":
            stem_top = max(stem_bottom - 4, stem_top)
        elif stem == "twisted":
            lean = -1
        elif stem == "bent":
            lean *= 2
        elif stem == "wide":
            stem_width += 2
        mid_x = stem_x + lean
        top_x = stem_x + lean * 2 if stem == "bent" else mid_x
        draw.polygon(((stem_x - stem_width // 2, stem_bottom), (mid_x - stem_width // 2, stem_mid),
                      (top_x - stem_width // 2, stem_top), (top_x + stem_width // 2, stem_top),
                      (mid_x + stem_width // 2, stem_mid), (stem_x + stem_width // 2, stem_bottom)),
                     fill=(48, 61, 30), outline=(27, 38, 21))
        if stem == "twisted":
            draw.line((stem_x, stem_bottom - 1, stem_x + 1, stem_mid, stem_x, stem_top + 1), fill=(77, 76, 34))


def fitted_feature(asset, max_width, max_height):
    feature = asset.copy()
    feature.thumbnail((max_width, max_height), Image.Resampling.NEAREST)
    return feature


def positioned_face_feature(pumpkin, asset, vertical_position, feature_height):
    x, y = pumpkin["x"], pumpkin["y"]
    width = pumpkin["width"]
    body_top = y + 3
    body_height = pumpkin["bottom"] - body_top
    inset = max(1, round(width * 0.12))
    face_width = max(1, width - 2 * inset)
    available_height = max(3, body_height - 2)
    max_height = max(1, round(available_height * feature_height))
    feature = fitted_feature(asset, face_width, max_height)
    feature_x = x + (width - feature.width) // 2
    feature_y = body_top + round(body_height * vertical_position)
    feature_y = min(max(body_top + 1, feature_y), pumpkin["bottom"] - feature.height - 1)
    return feature, feature_x, feature_y


def choose_drawable_eyes(pumpkin, assets):
    body_mask = pumpkin_body_mask(pumpkin)
    candidates = list(FACE_ASSETS["eyes"])
    random.shuffle(candidates)
    for asset_name in candidates:
        feature, x, y = positioned_face_feature(pumpkin, assets["eyes"][asset_name], 0.16, 0.27)
        body_region = body_mask.crop((x, y, x + feature.width, y + feature.height))
        visible_pixels = ImageChops.multiply(feature.getchannel("A"), body_region)
        if sum(pixel > 0 for pixel in visible_pixels.getdata()) >= MIN_DRAWABLE_EYE_PIXELS:
            return asset_name
    raise ValueError(f"No Halloween eye asset has at least {MIN_DRAWABLE_EYE_PIXELS} drawable pixels for pumpkin width {pumpkin['width']}")


def face_mask(pumpkin, assets):
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    features = [("eyes", "eyes", 0.16, 0.27), ("mouth", "mouth", 0.64, 0.27)]
    if pumpkin["nose"] is not None:
        features.insert(1, ("nose", "nose", 0.46, 0.14))

    for name, category, vertical_position, feature_height in features:
        asset_name = pumpkin[name]
        feature, feature_x, feature_y = positioned_face_feature(
            pumpkin, assets[category][asset_name], vertical_position, feature_height
        )
        if name == "mouth":
            if pumpkin["mouth_flip_left_right"]:
                feature = feature.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            if pumpkin["mouth_flip_top_bottom"]:
                feature = feature.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        mask.paste(feature.getchannel("A"), (feature_x, feature_y))
    return ImageChops.multiply(mask, pumpkin_body_mask(pumpkin))


def prepare_face_layers(pumpkins, assets):
    layers = []
    for pumpkin in pumpkins:
        cutout = face_mask(pumpkin, assets)
        bounds = cutout.getbbox()
        spark_points = []
        if bounds:
            spark_points = [(x, y) for y in range(bounds[1], bounds[3]) for x in range(bounds[0], bounds[2]) if cutout.getpixel((x, y))]
        layers.append({
            "cutout": cutout,
            "body": pumpkin_body_mask(pumpkin),
            "spark_points": spark_points,
            "edge": ImageChops.subtract(cutout.filter(ImageFilter.MaxFilter(3)), cutout),
            "warm_glow": cutout.filter(ImageFilter.GaussianBlur(4)),
            "close_glow": cutout.filter(ImageFilter.GaussianBlur(1.5)),
        })
    return layers


def new_flame():
    now = time.perf_counter()
    return {
        "phase": random.uniform(0, math.tau),
        "level": random.uniform(0.55, 0.9),
        "target": random.uniform(0.22, 1.0),
        "sway": random.uniform(-1, 1),
        "sway_target": random.uniform(-1, 1),
        "updated": now,
        "next_change": now + random.uniform(*FLAME_CHANGE_INTERVAL),
        "dip": 0.0,
        "next_dip": now + random.uniform(0.5, 1.2),
        "sparks": [],
        "next_spark": now + random.uniform(*FLAME_SPARK_INTERVAL),
        "elapsed": 0.0,
    }


def flame_intensity(flame, now):
    elapsed = max(0.0, now - flame["updated"])
    flame["updated"] = now
    flame["elapsed"] = elapsed
    if now >= flame["next_change"]:
        flame["target"] = random.uniform(0.3, 0.9)
        flame["sway_target"] = random.uniform(-1, 1)
        flame["next_change"] = now + random.uniform(*FLAME_CHANGE_INTERVAL)
    flame["dip"] *= math.exp(-elapsed / 0.12)
    if now >= flame["next_dip"]:
        # Occasional small dips keep the candle lively without a fire-like flare.
        if random.random() < 0.25:
            flame["dip"] = max(flame["dip"], random.uniform(0.35, 0.65))
        flame["next_dip"] = now + random.uniform(0.5, 1.2)

    # Larger response times make brightness and sway settle more slowly.
    flame["level"] += (flame["target"] - flame["level"]) * (1 - math.exp(-elapsed / 0.07))
    flame["sway"] += (flame["sway_target"] - flame["sway"]) * (1 - math.exp(-elapsed / 0.16))
    phase = flame["phase"]
    # These time multipliers set the small brightness ripples; reduce them for slower flicker.
    turbulent = (
        0.18 * math.sin(now * 8 + phase)
        + 0.1 * math.sin(now * 14 + phase * 2.1)
        + 0.05 * math.sin(now * 21 + phase * 3.4)
    )
    flicker = flame["level"] + turbulent - flame["dip"]
    return max(0.12, min(1.0, flicker))


def color_layer(mask, color, opacity):
    layer = Image.new("RGBA", mask.size, (*color, 0))
    layer.putalpha(mask.point(lambda value: round(value * opacity)))
    return layer


def render_frame(background, pumpkins, flames, face_layers, now):
    frame = background.copy()
    for pumpkin in pumpkins:
        draw_pumpkin(frame, pumpkin)

    frame = frame.convert("RGBA")
    for pumpkin, flame, layers in zip(pumpkins, flames, face_layers):
        intensity = flame_intensity(flame, now)
        glow_strength = 0.2 + 0.8 * intensity
        frame = Image.alpha_composite(frame, color_layer(layers["warm_glow"], (255, 33, 1), 0.82 * glow_strength))
        frame = Image.alpha_composite(frame, color_layer(layers["close_glow"], (255, 69, 1), 0.94 * glow_strength))
        frame = Image.alpha_composite(frame, color_layer(layers["edge"], (52, 13, 5), 0.92))
        light = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        pixels = light.load()
        alpha = layers["cutout"]
        bounds = alpha.getbbox()
        if bounds:
            for py in range(bounds[1], bounds[3]):
                for px in range(bounds[0], bounds[2]):
                    coverage = alpha.getpixel((px, py))
                    if not coverage:
                        continue
                    local_x = px - pumpkin["x"]
                    local_y = py - (pumpkin["y"] + 3)
                    # The time multipliers control how quickly the glow moves across the face.
                    wave = (
                        0.5
                        + 0.25 * math.sin(now * 8 + local_x * 1.4 - flame["sway"] + flame["phase"])
                        + 0.16 * math.sin(now * 14 - local_y * 1.1 + local_x * 0.7 - flame["sway"] * 2 + flame["phase"] * 2)
                        + 0.09 * math.sin(now * 5 + local_y * 1.8 + flame["phase"] * 3)
                    )
                    heat = max(0.0, min(1.0, intensity * (0.35 + 0.65 * wave)))
                    # Keep a bright candle-yellow core while the existing heat signal flickers it.
                    brightness = 0.35 + 0.65 * heat
                    color = (255, round(145 + heat * 110), round(3 + heat * 25), round(coverage * brightness))
                    pixels[px, py] = color
        frame = Image.alpha_composite(frame, light)

        # One short-lived ember at a time reads as a candle, not a fire.
        if now >= flame["next_spark"] and layers["spark_points"] and not flame["sparks"]:
            spark_x, spark_y = random.choice(layers["spark_points"])
            flame["sparks"].append({
                "x": spark_x - pumpkin["x"],
                "y": spark_y - (pumpkin["y"] + 3),
                "vx": random.uniform(-2.5, 2.5),
                "vy": random.uniform(-7.0, -2.5),
                "age": 0.0,
                "life": random.uniform(0.18, 0.32),
            })
            flame["next_spark"] = now + random.uniform(*FLAME_SPARK_INTERVAL)

        spark_draw = ImageDraw.Draw(frame)
        for spark in flame["sparks"]:
            spark["age"] += flame["elapsed"]
            spark["x"] += spark["vx"] * flame["elapsed"]
            spark["y"] += spark["vy"] * flame["elapsed"]
            if spark["age"] >= spark["life"]:
                continue
            spark_x = pumpkin["x"] + round(spark["x"])
            spark_y = pumpkin["y"] + 3 + round(spark["y"])
            if (0 <= spark_x < WIDTH and 0 <= spark_y < HEIGHT
                    and layers["body"].getpixel((spark_x, spark_y))):
                brightness = 1 - spark["age"] / spark["life"]
                spark_draw.point((spark_x, spark_y), fill=(255, round(125 + 130 * brightness), round(12 + 42 * brightness), 255))
        flame["sparks"] = [spark for spark in flame["sparks"] if spark["age"] < spark["life"]]
    return frame.convert("RGB")


@planesign_mode_handler(DisplayMode.HALLOWEEN)
def halloween_mode(sign):
    background = draw_background()
    assets = load_face_assets()
    pumpkins = create_pumpkins(assets)
    face_layers = prepare_face_layers(pumpkins, assets)
    flames = [new_flame() for _ in pumpkins]
    next_scene = time.perf_counter() + random.uniform(20.0, 35.0)

    while shared_config.shared_mode.value == DisplayMode.HALLOWEEN.value:
        now = time.perf_counter()
        if now >= next_scene:
            pumpkins = create_pumpkins(assets)
            face_layers = prepare_face_layers(pumpkins, assets)
            flames = [new_flame() for _ in pumpkins]
            next_scene = now + random.uniform(20.0, 35.0)

        sign.canvas.SetImage(render_frame(background, pumpkins, flames, face_layers, now), 0, 0)
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()
        if sign.wait_loop(0.05):
            break
