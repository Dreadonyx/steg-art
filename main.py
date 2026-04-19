"""
Steg-Art Generator — FastAPI backend
Flow: message + style → Groq enhances prompt → HuggingFace FLUX → LSB embed → return PNG
"""

import os, base64, httpx, subprocess, uuid, tempfile as _tmp
from pathlib import Path
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

# ── terminal session store ────────────────────────────────────────────────────
_TERM_DIR = Path(_tmp.gettempdir()) / "stegterm"
_TERM_DIR.mkdir(exist_ok=True)
_TERM_SESSIONS: dict[str, dict] = {}   # session_id → {path, name}

GROQ_KEY = os.getenv("GROQ_API_KEY")
HF_KEY   = os.getenv("HF_API_KEY")
OR_KEY   = os.getenv("OPENROUTER_API_KEY")

groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None


# ── models ────────────────────────────────────────────────────────────────────

class EncodeRequest(BaseModel):
    message: str
    style: str
    extra_prompt: str = ""

class TermRunRequest(BaseModel):
    session_id: str
    command: str


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
        result = steg.extract(img_bytes)
        return JSONResponse(result)
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


# ── terminal routes ───────────────────────────────────────────────────────────

@app.post("/terminal/upload")
async def terminal_upload(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "Upload an image file.")
    session_id = str(uuid.uuid4())
    suffix = Path(file.filename or "image.png").suffix or ".png"
    dest = _TERM_DIR / f"{session_id}{suffix}"
    dest.write_bytes(await file.read())
    _TERM_SESSIONS[session_id] = {"path": dest, "name": file.filename or "image.png"}
    return {"session_id": session_id, "filename": file.filename or "image.png"}


@app.post("/terminal/run")
async def terminal_run(req: TermRunRequest):
    sess = _TERM_SESSIONS.get(req.session_id)
    if not sess or not sess["path"].exists():
        return {"output": "No image loaded. Drop an image above first.", "clear": False}
    result = _run_steg_cmd(req.command.strip(), sess["path"])
    clear = result == "__clear__"
    return {"output": "" if clear else result, "clear": clear}


# ── terminal command engine ───────────────────────────────────────────────────

_TERM_HELP = """\
┌─────────────────────────────────────────────┐
│          steg-art terminal  v2.0            │
├─────────────────────────────────────────────┤
│  strings [-n N]    printable strings        │
│  binwalk           embedded file scan       │
│  steghide info     steghide metadata        │
│  steghide extract -p <pass>                 │
│  stegseek          brute-force steghide     │
│  exiftool          EXIF / metadata          │
│  xxd [-l N]        hex dump                 │
│  file              detect file type         │
│  zsteg [-a]        LSB steg detection       │
│  base64            base64-encode image      │
│  md5sum            MD5 hash                 │
│  sha256sum         SHA-256 hash             │
│  clear             clear terminal           │
│  help              show this help           │
└─────────────────────────────────────────────┘"""


def _exec(cmd: list, timeout: int = 15, cwd=None, inp: str | None = None) -> str:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd, input=inp,
        )
        return (r.stdout + r.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s"
    except FileNotFoundError:
        return f"{cmd[0]}: not installed on this system"
    except Exception as e:
        return f"Error: {e}"


def _run_steg_cmd(command: str, img: Path) -> str:
    parts = command.split()
    if not parts:
        return ""
    cmd, args = parts[0].lower(), parts[1:]

    if cmd == "help":
        return _TERM_HELP

    if cmd == "clear":
        return "__clear__"

    if cmd == "strings":
        filtered, i = [], 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args) and args[i + 1].isdigit():
                filtered += ["-n", args[i + 1]]; i += 2
            elif args[i].startswith("-") and args[i][1:].isdigit():
                filtered.append(args[i]); i += 1
            else:
                i += 1
        return _exec(["strings"] + filtered + [str(img)])

    if cmd == "binwalk":
        allowed = {"-B", "-A", "--opcodes", "-q", "--quiet", "-v", "--verbose"}
        return _exec(["binwalk"] + [a for a in args if a in allowed] + [str(img)], timeout=20)

    if cmd == "steghide":
        sub = args[0] if args else "info"
        if sub == "info":
            return _exec(["steghide", "info", "-sf", str(img)], inp="\n")
        if sub == "extract":
            password = ""
            if "-p" in args:
                idx = args.index("-p")
                if idx + 1 < len(args):
                    password = args[idx + 1]
            with _tmp.TemporaryDirectory() as td:
                r = subprocess.run(
                    ["steghide", "extract", "-sf", str(img), "-p", password, "-f"],
                    capture_output=True, text=True, timeout=10, cwd=td,
                )
                out = (r.stdout + r.stderr).strip()
                extracted = list(Path(td).iterdir())
                if extracted:
                    try:
                        content = extracted[0].read_text(errors="replace")
                        out += f"\n\n── extracted content ──\n{content}"
                    except Exception:
                        out += "\n(binary payload — not displayable as text)"
                return out or "(no output)"
        return "Usage:\n  steghide info\n  steghide extract -p <password>"

    if cmd == "stegseek":
        wl = "/usr/share/wordlists/rockyou.txt"
        if not Path(wl).exists():
            return "stegseek: /usr/share/wordlists/rockyou.txt not found\nTip: sudo apt install wordlists"
        with _tmp.TemporaryDirectory() as td:
            r = subprocess.run(
                ["stegseek", str(img), wl],
                capture_output=True, text=True, timeout=60, cwd=td,
            )
            out = (r.stdout + r.stderr).strip()
            extracted = list(Path(td).iterdir())
            if extracted:
                try:
                    content = extracted[0].read_text(errors="replace")
                    out += f"\n\n── extracted content ──\n{content}"
                except Exception:
                    pass
            return out or "(no output)"

    if cmd == "exiftool":
        return _exec(["exiftool", str(img)])

    if cmd == "xxd":
        filtered, i = [], 0
        while i < len(args):
            if args[i] in ("-l", "-s", "-c", "-g") and i + 1 < len(args):
                filtered += [args[i], args[i + 1]]; i += 2
            else:
                i += 1
        raw = _exec(["xxd"] + filtered + [str(img)], timeout=10)
        lines = raw.split("\n")
        if len(lines) > 80:
            return "\n".join(lines[:80]) + f"\n\n[… {len(lines)-80} more lines — use -l <bytes> to limit]"
        return raw

    if cmd == "file":
        return _exec(["file", str(img)])

    if cmd == "zsteg":
        allowed = {"-a", "--all", "-v", "--verbose"}
        return _exec(["zsteg"] + [a for a in args if a in allowed] + [str(img)], timeout=20)

    if cmd == "base64":
        raw = _exec(["base64", str(img)], timeout=10)
        lines = raw.split("\n")
        if len(lines) > 10:
            return "\n".join(lines[:10]) + "\n[… truncated]"
        return raw

    if cmd in ("md5sum", "sha256sum"):
        return _exec([cmd, str(img)])

    return f"{cmd}: command not found\nType 'help' for available commands."
