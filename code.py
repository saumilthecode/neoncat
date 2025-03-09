import gc
import time
import board
import displayio
import framebufferio
import rgbmatrix
import wifi
import socketpool
import ssl
import adafruit_requests
import io
from jpegio import JpegDecoder

# --- Wi‑Fi and Requests Setup ---
pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

# --- Display and Image Settings ---
TARGET_WIDTH = 64
TARGET_HEIGHT = 32
PALETTE_SIZE = 16

FIXED_PALETTE = [
    (0, 0, 0),       # Black
    (128, 128, 128), # Gray
    (255, 255, 255), # White
    (255, 0, 0),     # Red
    (0, 255, 0),     # Green
    (0, 0, 255),     # Blue
    (255, 255, 0),   # Yellow
    (0, 255, 255),   # Cyan
    (255, 0, 255),   # Magenta
    (128, 0, 0),     # Dark Red
    (0, 128, 0),     # Dark Green
    (0, 0, 128),     # Dark Blue
    (128, 128, 0),   # Olive
    (0, 128, 128),   # Teal
    (128, 0, 128),   # Purple
    (192, 192, 192)  # Silver
]

def nearest_color(pixel):
    """Return the index of the color in FIXED_PALETTE closest to the given (R, G, B) tuple."""
    r, g, b = pixel
    best_index = 0
    best_distance = 1e9
    for i, (pr, pg, pb) in enumerate(FIXED_PALETTE):
        dr = r - pr
        dg = g - pg
        db = b - pb
        distance = dr * dr + dg * dg + db * db
        if distance < best_distance:
            best_distance = distance
            best_index = i
    return best_index

def rgb565_to_rgb(pixel):
    """Convert a 16-bit RGB565 pixel to an (R, G, B) tuple scaled 0-255."""
    red   = (pixel >> 11) & 0x1F
    green = (pixel >> 5) & 0x3F
    blue  = pixel & 0x1F
    r8 = (red * 255) // 31
    g8 = (green * 255) // 63
    b8 = (blue * 255) // 31
    return (r8, g8, b8)

def decode_and_quantize_jpeg(jpeg_data, brightness_factor=0.8):
    """
    Decode the JPEG data into a displayio.Bitmap, then for each pixel:
      - Convert from RGB565 to (R, G, B),
      - Adjust brightness,
      - Quantize to the nearest FIXED_PALETTE index.
    Returns: (width, height, quantized) where quantized is a bytearray of palette indices.
    """
    gc.collect()  # Free memory before starting.
    # Ensure the JPEG has an end-of-image marker.
    if not jpeg_data.endswith(b'\xff\xd9'):
        jpeg_data += b'\xff\xd9'
    jpeg_file = io.BytesIO(jpeg_data)
    decoder = JpegDecoder()
    # Open JPEG; note the expected tuple is (width, height)
    width, height = decoder.open(jpeg_file)
    bitmap = displayio.Bitmap(width, height, 65536)
    decoder.decode(bitmap)
    
    quantized = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            pixel565 = bitmap[x, y]
            r, g, b = rgb565_to_rgb(pixel565)
            # Adjust brightness
            r = int(r * brightness_factor)
            g = int(g * brightness_factor)
            b = int(b * brightness_factor)
            quantized[y * width + x] = nearest_color((r, g, b))
    return width, height, quantized

def resize_quantized(width, height, quantized, target_width, target_height):
    """Resize the quantized image (stored as a bytearray) using nearest-neighbor scaling."""
    new_quant = bytearray(target_width * target_height)
    for y in range(target_height):
        src_y = int(y * height / target_height)
        for x in range(target_width):
            src_x = int(x * width / target_width)
            new_quant[y * target_width + x] = quantized[src_y * width + src_x]
    return new_quant

def fetch_cat_image():
    """
    Fetch a JPEG cat image from the API.
    The URL includes query parameters to request an image roughly at the target size.
    """
    url = "https://cataas.com/cat?width={}&height={}".format(TARGET_WIDTH, TARGET_HEIGHT)
    response = requests.get(url)
    jpeg_data = response.content
    response.close()
    return jpeg_data

def get_cat_image_data():
    """
    Try fetching, decoding, and quantizing the cat image up to 3 times.
    If decoding fails due to a malformed JPEG stream, fall back to a checkerboard pattern.
    Returns:
      - palette: FIXED_PALETTE (list of (R, G, B) tuples)
      - quantized: a bytearray of pixel indices.
    """
    attempts = 3
    for i in range(attempts):
        try:
            jpeg_data = fetch_cat_image()
            width, height, quantized = decode_and_quantize_jpeg(jpeg_data, brightness_factor=0.8)
            if width != TARGET_WIDTH or height != TARGET_HEIGHT:
                quantized = resize_quantized(width, height, quantized, TARGET_WIDTH, TARGET_HEIGHT)
            return FIXED_PALETTE, quantized
        except RuntimeError as e:
            print("Attempt", i+1, "failed:", e)
            time.sleep(1)
    # Fallback pattern: checkerboard.
    print("Using fallback pattern")
    fallback = bytearray(TARGET_WIDTH * TARGET_HEIGHT)
    for y in range(TARGET_HEIGHT):
        for x in range(TARGET_WIDTH):
            fallback[y * TARGET_WIDTH + x] = 1 if (x + y) % 2 else 0
    fallback_palette = [(0, 0, 0), (255, 255, 255)] + [(0, 0, 0)] * (PALETTE_SIZE - 2)
    return fallback_palette, fallback

# --- Display Setup ---
displayio.release_displays()

matrix = rgbmatrix.RGBMatrix(
    width=TARGET_WIDTH,
    height=TARGET_HEIGHT,
    bit_depth=4,  # 4-bit depth gives 16 colors.
    rgb_pins=[board.IO1, board.IO2, board.IO3, board.IO5, board.IO4, board.IO6],
    addr_pins=[board.IO8, board.IO7, board.IO10, board.IO9],
    clock_pin=board.IO12,
    latch_pin=board.IO11,
    output_enable_pin=board.IO13
)

display = framebufferio.FramebufferDisplay(matrix, auto_refresh=False)

# --- Main Loop ---
while True:
    palette, quantized_pixels = get_cat_image_data()
    bitmap_cat = displayio.Bitmap(TARGET_WIDTH, TARGET_HEIGHT, PALETTE_SIZE)
    for y in range(TARGET_HEIGHT):
        for x in range(TARGET_WIDTH):
            bitmap_cat[x, y] = quantized_pixels[y * TARGET_WIDTH + x]
    pal_cat = displayio.Palette(PALETTE_SIZE)
    for i, (r, g, b) in enumerate(palette):
        pal_cat[i] = (r << 16) | (g << 8) | b
    tg_cat = displayio.TileGrid(bitmap_cat, pixel_shader=pal_cat)
    group_cat = displayio.Group()
    group_cat.append(tg_cat)
    display.root_group = group_cat
    display.refresh(minimum_frames_per_second=0)
    time.sleep(3)
