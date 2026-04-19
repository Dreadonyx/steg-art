"""
Steg-Art Generator — FastAPI backend
Flow: message + style → Groq enhances prompt → HuggingFace FLUX → LSB embed → return PNG
"""

import os, base64, httpx
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
import steg

load_dotenv()

app = FastAPI(title="Steg-Art")
app.mount("/static", StaticFiles(directory="static"), name="static")

GROQ_KEY = os.getenv("GROQ_API_KEY")
HF_KEY   = os.getenv("HF_API_KEY")
OR_KEY   = os.getenv("OPENROUTER_API_KEY")

groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None


# ── models ────────────────────────────────────────────────────────────────────

class EncodeRequest(BaseModel):
    message: str
    style: str
    extra_prompt: str = ""


# ── helpers ───────────────────────────────────────────────────────────────────

def enhance_prompt(style: str, extra: str) -> str:
    if not groq_client:
        return f"{style}. {extra}. High quality digital art, detailed, 4k."

    resp = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": (
                "You are an expert at writing image generation prompts. "
                "Turn the user's art style into a vivid, detailed, atmospheric prompt "
                "for an AI image generator. Under 150 words. Return ONLY the prompt."
            )},
            {"role": "user", "content": f"Style: {style}" + (f"\nExtra: {extra}" if extra else "")},
        ],
        max_tokens=200,
        temperature=0.9,
    )
    return resp.choices[0].message.content.strip()


def generate_image_hf(prompt: str) -> bytes:
    """Generate image via HuggingFace Inference API — FLUX.1-schnell (free)."""
    r = httpx.post(
        "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
        headers={
            "Authorization": f"Bearer {HF_KEY}",
            "Content-Type": "application/json",
        },
        json={"inputs": prompt},
        timeout=120,
    )
    r.raise_for_status()
    return r.content


def generate_image_openrouter(prompt: str) -> bytes:
    """Generate image via OpenRouter — Gemini image model."""
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OR_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "google/gemini-3.1-flash-image-preview",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": f"Generate an image: {prompt}"}],
        },
        timeout=90,
    )
    r.raise_for_status()
    data = r.json()
    images = data["choices"][0]["message"].get("images", [])
    if not images:
        raise ValueError("OpenRouter returned no image.")
    url = images[0]["image_url"]["url"]
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    img_r = httpx.get(url, timeout=30)
    img_r.raise_for_status()
    return img_r.content


def generate_image(prompt: str) -> bytes:
    """Try HuggingFace FLUX first, fall back to OpenRouter."""
    if HF_KEY:
        try:
            return generate_image_hf(prompt)
        except Exception as e:
            print(f"[HF failed] {e}")

    if OR_KEY:
        try:
            return generate_image_openrouter(prompt)
        except Exception as e:
            print(f"[OpenRouter failed] {e}")

    raise HTTPException(503, "No image generation API available. Add HF_API_KEY to .env")


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/encode")
async def encode(req: EncodeRequest):
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty.")
    if not req.style.strip():
        raise HTTPException(400, "Art style cannot be empty.")
    try:
        enhanced  = enhance_prompt(req.style, req.extra_prompt)
        print(f"[Prompt] {enhanced[:80]}...")
        img_bytes = generate_image(enhanced)
        steg_bytes = steg.embed(img_bytes, req.message)
        return JSONResponse({
            "image_b64":      base64.b64encode(steg_bytes).decode(),
            "enhanced_prompt": enhanced,
            "image_size_kb":  round(len(steg_bytes) / 1024, 1),
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/decode")
async def decode(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "Upload an image file.")
    img_bytes = await file.read()
    try:
        return JSONResponse({"message": steg.extract(img_bytes)})
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/health")
def health():
    return {
        "groq":        bool(groq_client),
        "huggingface": bool(HF_KEY),
        "openrouter":  bool(OR_KEY),
    }
