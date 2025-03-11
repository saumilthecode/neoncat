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
import microcontroller
import supervisor
from jpegio import JpegDecoder

# --- Configuration ---
TARGET_WIDTH = 64
TARGET_HEIGHT = 32
PALETTE_SIZE = 16
BRIGHTNESS_FACTOR = 0.8
IMAGE_DISPLAY_DURATION = 3  # seconds
MIN_FREE_RAM = 35000  # threshold in bytes to trigger a reload

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

def print_system_status():
    """Prints system temperature (in Celsius) and available memory."""
    try:
        cpu_temperature = microcontroller.cpu.temperature
        print(f"CPU Temperature: {cpu_temperature:.2f} °C")
    except AttributeError:
        print("CPU Temperature: Not available on this ESP32 variant.")
    print(f"Free RAM: {gc.mem_free()} bytes")

def graceful_reload():
    """Reloads the script instead of crashing on errors."""
    print("\nRestarting...")
    time.sleep(1)
    supervisor.reload()

def nearest_color(pixel):
    """Return the index of the color in FIXED_PALETTE closest to the given (R, G, B) tuple."""
    r, g, b = pixel
    best_index = 0
    best_distance = float('inf')
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

def decode_and_quantize_jpeg(jpeg_data, brightness_factor=1.0):
    """
    Decode the JPEG data into a displayio.Bitmap, adjust brightness,
    and quantize to the nearest FIXED_PALETTE index.
    Returns: (width, height, quantized) where quantized is a bytearray of palette indices.
    """
    gc.collect()  # Clean memory before starting.
    if not jpeg_data.endswith(b'\xff\xd9'):
        jpeg_data += b'\xff\xd9'
    jpeg_file = io.BytesIO(jpeg_data)
    decoder = JpegDecoder()
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
    # Clean up temporary objects.
    del bitmap, decoder, jpeg_file
    gc.collect()
    return width, height, quantized

def resize_quantized(width, height, quantized, target_width, target_height):
    """Resize the quantized image using nearest-neighbor scaling."""
    new_quant = bytearray(target_width * target_height)
    for y in range(target_height):
        src_y = int(y * height / target_height)
        for x in range(target_width):
            src_x = int(x * width / target_width)
            new_quant[y * target_width + x] = quantized[src_y * width + src_x]
    return new_quant

def fetch_cat_image():
    """Fetch a JPEG cat image from the API."""
    url = f"https://cataas.com/cat?width={TARGET_WIDTH}&height={TARGET_HEIGHT}"
    response = requests.get(url)
    jpeg_data = response.content
    response.close()
    return jpeg_data

def get_cat_image_data():
    """
    Try fetching, decoding, and quantizing the cat image up to 3 times.
    If decoding fails, fall back to a checkerboard pattern.
    Returns:
      - palette: list of (R, G, B) tuples.
      - quantized: a bytearray of pixel indices.
    """
    attempts = 3
    for i in range(attempts):
        try:
            jpeg_data = fetch_cat_image()
            width, height, quantized = decode_and_quantize_jpeg(jpeg_data, brightness_factor=BRIGHTNESS_FACTOR)
            if width != TARGET_WIDTH or height != TARGET_HEIGHT:
                quantized = resize_quantized(width, height, quantized, TARGET_WIDTH, TARGET_HEIGHT)
            gc.collect()
            return FIXED_PALETTE, quantized
        except RuntimeError as e:
            print("Attempt", i + 1, "failed:", e)
            time.sleep(1)
    print("Using fallback pattern")
    fallback = bytearray(TARGET_WIDTH * TARGET_HEIGHT)
    for y in range(TARGET_HEIGHT):
        for x in range(TARGET_WIDTH):
            fallback[y * TARGET_WIDTH + x] = 1 if (x + y) % 2 else 0
    fallback_palette = [(0, 0, 0), (255, 255, 255)] + [(0, 0, 0)] * (PALETTE_SIZE - 2)
    gc.collect()
    return fallback_palette, fallback

# --- Wi‑Fi and Requests Setup ---
pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

# --- Display Setup ---
displayio.release_displays()
matrix = rgbmatrix.RGBMatrix(
    width=TARGET_WIDTH,
    height=TARGET_HEIGHT,
    bit_depth=4,
    rgb_pins=[board.IO1, board.IO2, board.IO3, board.IO5, board.IO4, board.IO6],
    addr_pins=[board.IO8, board.IO7, board.IO10, board.IO9],
    clock_pin=board.IO12,
    latch_pin=board.IO11,
    output_enable_pin=board.IO13
)
display = framebufferio.FramebufferDisplay(matrix, auto_refresh=False)

# --- Create and Reuse Display Objects ---
bitmap_cat = displayio.Bitmap(TARGET_WIDTH, TARGET_HEIGHT, PALETTE_SIZE)
pal_cat = displayio.Palette(PALETTE_SIZE)
for i, (r, g, b) in enumerate(FIXED_PALETTE):
    pal_cat[i] = (r << 16) | (g << 8) | b
tg_cat = displayio.TileGrid(bitmap_cat, pixel_shader=pal_cat)
group_cat = displayio.Group()
group_cat.append(tg_cat)
display.root_group = group_cat

# --- Main Loop ---
try:
    while True:
        gc.collect()
        free = gc.mem_free()
        print_system_status()
        if free < MIN_FREE_RAM:
            print("Low memory detected, reloading...")
            graceful_reload()

        palette, quantized_pixels = get_cat_image_data()

        # Update the bitmap with new image data.
        for y in range(TARGET_HEIGHT):
            for x in range(TARGET_WIDTH):
                bitmap_cat[x, y] = quantized_pixels[y * TARGET_WIDTH + x]

        # Update the palette in case the image has different colors.
        for i, (r, g, b) in enumerate(palette):
            pal_cat[i] = (r << 16) | (g << 8) | b

        display.refresh(minimum_frames_per_second=0)
        time.sleep(IMAGE_DISPLAY_DURATION)
        gc.collect()
except KeyboardInterrupt:
    graceful_reload()

