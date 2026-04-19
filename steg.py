"""
LSB Steganography engine — embed/extract arbitrary text in PNG images.
Uses the 2 least significant bits of R, G, B channels for capacity.
Supports region-based hiding (top-left, bottom-right, center, etc.)
"""

from PIL import Image
import io, base64

DELIMITER = "<<STEGEND>>"

# Region → (x0_frac, y0_frac, x1_frac, y1_frac)  fractions of image size
REGIONS = {
    "full":         None,
    "top-left":     (0.0,  0.0,  0.5,  0.5),
    "top-right":    (0.5,  0.0,  1.0,  0.5),
    "bottom-left":  (0.0,  0.5,  0.5,  1.0),
    "bottom-right": (0.5,  0.5,  1.0,  1.0),
    "center":       (0.25, 0.25, 0.75, 0.75),
}


def _text_to_bits(text: str) -> str:
    data = (text + DELIMITER).encode("utf-8")
    return "".join(f"{byte:08b}" for byte in data)


def _bits_to_text(bits: str) -> str:
    chars = []
    for i in range(0, len(bits), 8):
        byte = bits[i:i+8]
        if len(byte) < 8:
            break
        chars.append(chr(int(byte, 2)))
    raw = "".join(chars)
    if DELIMITER in raw:
        return raw[:raw.index(DELIMITER)]
    return raw


def _region_indices(width: int, height: int, region: str) -> list:
    """Return pixel indices for a named region."""
    bounds = REGIONS.get(region)
    if bounds is None:
        return list(range(width * height))
    x0f, y0f, x1f, y1f = bounds
    x0, y0 = int(x0f * width),  int(y0f * height)
    x1, y1 = int(x1f * width),  int(y1f * height)
    return [row * width + col for row in range(y0, y1) for col in range(x0, x1)]


def embed(image_bytes: bytes, message: str, region: str = "full") -> bytes:
    """Embed message into image bytes in the given region, return PNG bytes."""
    if region not in REGIONS:
        region = "full"

    img    = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h   = img.size
    pixels = list(img.getdata())

    indices  = _region_indices(w, h, region)
    bits     = _text_to_bits(message)
    capacity = len(indices) * 3 * 2   # 2 LSBs × 3 channels per pixel

    if len(bits) > capacity:
        raise ValueError(
            f"Message too long ({len(bits)} bits). "
            f"Region '{region}' capacity: ~{capacity // 8 - len(DELIMITER)} chars."
        )

    bit_idx    = 0
    new_pixels = list(pixels)

    for px_idx in indices:
        if bit_idx >= len(bits):
            break
        r, g, b, a = pixels[px_idx]
        new_ch = []
        for ch in (r, g, b):
            if bit_idx < len(bits):
                b1 = int(bits[bit_idx])
                b2 = int(bits[bit_idx + 1]) if bit_idx + 1 < len(bits) else 0
                ch = (ch & 0b11111100) | (b1 << 1) | b2
                bit_idx += 2
            new_ch.append(ch)
        new_pixels[px_idx] = (*new_ch, a)

    out = Image.new("RGBA", img.size)
    out.putdata(new_pixels)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def extract(image_bytes: bytes, region: str = "full") -> dict:
    """Extract hidden message from image, searching in the given region."""
    if region not in REGIONS:
        region = "full"

    img    = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    pixels = list(img.getdata())
    width, height = img.size
    total_pixels  = len(pixels)

    indices       = _region_indices(width, height, region)
    region_pixels = len(indices)
    capacity_bits = region_pixels * 3 * 2

    bits = []
    for px_idx in indices:
        r, g, b, _ = pixels[px_idx]
        for ch in (r, g, b):
            bits.append(str((ch >> 1) & 1))
            bits.append(str(ch & 1))

    chars, raw, found_at_bit = [], "", None
    for i in range(0, len(bits), 8):
        byte = bits[i:i+8]
        if len(byte) < 8:
            break
        chars.append(chr(int("".join(byte), 2)))
        raw = "".join(chars)
        if DELIMITER in raw:
            found_at_bit = i + 8
            break

    if not raw or DELIMITER not in raw:
        raise ValueError("No hidden message found in this image.")

    message = raw[:raw.index(DELIMITER)]
    if not message:
        raise ValueError("No hidden message found in this image.")

    # reject garbage: if >25% chars are non-printable it's a wrong region / no data
    non_printable = sum(1 for c in message if ord(c) < 32 and c not in '\n\r\t')
    if non_printable / len(message) > 0.25:
        raise ValueError("No hidden message found in this image.")

    msg_bits       = found_at_bit
    msg_bytes_count = msg_bits // 8
    pixels_used    = (msg_bits + 5) // 6
    capacity_chars = (capacity_bits // 8) - len(DELIMITER)
    pct_used       = round(pixels_used / region_pixels * 100, 2)

    last_ch_idx  = (msg_bits // 2) % 3
    channels_used = ["R", "G", "B"][:last_ch_idx + 1] if last_ch_idx < 2 else ["R", "G", "B"]

    start_px  = indices[0] + 1
    end_px    = indices[min(pixels_used - 1, len(indices) - 1)] + 1
    start_row = indices[0] // width + 1
    end_row   = indices[min(pixels_used - 1, len(indices) - 1)] // width + 1

    return {
        "message": message,
        "meta": {
            "method":         f"LSB (2 bits/channel)",
            "region":         region,
            "channels":       channels_used,
            "pixels_used":    pixels_used,
            "total_pixels":   total_pixels,
            "image_size":     f"{width} × {height}",
            "bits_used":      msg_bits,
            "bytes_used":     msg_bytes_count,
            "capacity_chars": capacity_chars,
            "pct_used":       pct_used,
            "pixel_range":    f"px {start_px} – {end_px}",
            "row_range":      f"row {start_row} – {end_row}",
            "bit_planes":     "LSB-1 and LSB-0 of R, G, B",
        },
    }


def image_to_b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode()


def b64_to_image(b64_str: str) -> bytes:
    return base64.b64decode(b64_str)
