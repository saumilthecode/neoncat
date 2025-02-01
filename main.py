import time
try:
    import urllib.request, io
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

TARGET_WIDTH = 64
TARGET_HEIGHT = 32
PALETTE_SIZE = 16

def generate_cat_image_data():
    url = "https://cataas.com/cat"
    response = urllib.request.urlopen(url)
    img_data = response.read()
    img = Image.open(io.BytesIO(img_data)).convert("RGB")
    img_fitted = ImageOps.fit(img, (TARGET_WIDTH, TARGET_HEIGHT), method=Image.BICUBIC)
    img_paletted = img_fitted.convert("P", palette=Image.ADAPTIVE, colors=PALETTE_SIZE)
    raw_palette = img_paletted.getpalette()[:PALETTE_SIZE * 3]
    palette = []
    for i in range(0, len(raw_palette), 3):
        r, g, b = raw_palette[i:i+3]
        palette.append((r << 16) | (g << 8) | b)
    pixels = list(img_paletted.getdata())
    if len(pixels) != TARGET_WIDTH * TARGET_HEIGHT:
        raise ValueError("Pixel data length mismatch!")
    return palette, pixels

def get_cat_image():
    if HAS_PIL:
        try:
            return generate_cat_image_data()
        except Exception as e:
            print("Error fetching cat image:", e)
    fallback_palette = [0x000000, 0xffffff] + [0x000000] * (PALETTE_SIZE - 2)
    fallback_pixels = []
    for y in range(TARGET_HEIGHT):
        for x in range(TARGET_WIDTH):
            fallback_pixels.append(1 if (x + y) % 2 else 0)
    return fallback_palette, fallback_pixels

import board, displayio, framebufferio, rgbmatrix

displayio.release_displays()

matrix = rgbmatrix.RGBMatrix(
    width=TARGET_WIDTH, height=TARGET_HEIGHT, bit_depth=4,
    rgb_pins=[board.D6, board.D5, board.D9, board.D11, board.D10, board.D12],
    addr_pins=[board.A5, board.A4, board.A3, board.A2],
    clock_pin=board.D13, latch_pin=board.D0, output_enable_pin=board.D1
)

display = framebufferio.FramebufferDisplay(matrix, auto_refresh=True)

while True:
    CAT_PALETTE, CAT_PIXELS = get_cat_image()
    bitmap_cat = displayio.Bitmap(TARGET_WIDTH, TARGET_HEIGHT, PALETTE_SIZE)
    if len(CAT_PIXELS) != TARGET_WIDTH * TARGET_HEIGHT:
        raise IndexError("CAT_PIXELS length does not match TARGET_WIDTH * TARGET_HEIGHT!")
    for y in range(TARGET_HEIGHT):
        for x in range(TARGET_WIDTH):
            bitmap_cat[x, y] = CAT_PIXELS[y * TARGET_WIDTH + x]
    pal_cat = displayio.Palette(PALETTE_SIZE)
    for i, color in enumerate(CAT_PALETTE):
        pal_cat[i] = color
    tg_cat = displayio.TileGrid(bitmap_cat, pixel_shader=pal_cat)
    group_cat = displayio.Group()
    group_cat.append(tg_cat)
    display.root_group = group_cat
    time.sleep(3)
