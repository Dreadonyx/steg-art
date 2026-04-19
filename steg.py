"""
LSB Steganography engine — embed/extract arbitrary text in PNG images.
Uses the 2 least significant bits of R, G, B channels for capacity.
"""

from PIL import Image
import io, base64

DELIMITER = "<<STEGEND>>"

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

def embed(image_bytes: bytes, message: str) -> bytes:
    """Embed message into image bytes, return PNG bytes."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    pixels = list(img.getdata())

    bits = _text_to_bits(message)
    capacity = len(pixels) * 3 * 2  # 2 LSBs per R,G,B channel

    if len(bits) > capacity:
        raise ValueError(
            f"Message too long ({len(bits)} bits) for image capacity ({capacity} bits). "
            f"Max ~{capacity // 8 - len(DELIMITER)} characters."
        )

    bit_idx = 0
    new_pixels = []

    for pixel in pixels:
        r, g, b, a = pixel
        channels = [r, g, b]
        new_channels = []

        for ch in channels:
            if bit_idx < len(bits):
                # embed 2 bits
                b1 = int(bits[bit_idx])
                b2 = int(bits[bit_idx + 1]) if bit_idx + 1 < len(bits) else 0
                # clear 2 LSBs and set them
                ch = (ch & 0b11111100) | (b1 << 1) | b2
                bit_idx += 2
            new_channels.append(ch)

        new_pixels.append((*new_channels, a))

    out_img = Image.new("RGBA", img.size)
    out_img.putdata(new_pixels)

    buf = io.BytesIO()
    out_img.save(buf, format="PNG")
    return buf.getvalue()

def extract(image_bytes: bytes) -> str:
    """Extract hidden message from image bytes."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    pixels = list(img.getdata())

    bits = []
    for pixel in pixels:
        r, g, b, _ = pixel
        for ch in [r, g, b]:
            bits.append(str((ch >> 1) & 1))
            bits.append(str(ch & 1))

    text = _bits_to_text("".join(bits))
    if not text:
        raise ValueError("No hidden message found in this image.")
    return text

def image_to_b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode()

def b64_to_image(b64_str: str) -> bytes:
    return base64.b64decode(b64_str)
