# steg-art 

> Hide messages inside AI-generated art. The image looks normal. The secret isn't.

You give it a message and an art style. It generates an image via FLUX AI, embeds your message using LSB steganography, and hands you back a PNG that looks completely clean to anyone who sees it.

## Pipeline

```
your message + art style
       ↓
Groq enhances the prompt (LLaMA-3.3-70b)
       ↓
FLUX.1-schnell generates the image (HuggingFace)
       ↓
LSB steganography embeds your message
       ↓
you get a PNG with a hidden secret
```

To decode: upload the image → get the message back.

## Setup

```bash
git clone https://github.com/Dreadonyx/steg-art
cd steg-art
pip install -r requirements.txt
cp .env.example .env
# add Groq, HuggingFace, and OpenRouter keys
python main.py
```

Open `http://localhost:8000`.

## API

```
POST /encode   → message + style → steganographic PNG
POST /decode   → image upload → extracted hidden message
GET  /health   → shows which APIs are active
```

## Stack

- Python / FastAPI
- Groq API (LLaMA-3.3-70b) — prompt enhancement
- HuggingFace FLUX.1-schnell — image generation
- OpenRouter Gemini — fallback if HuggingFace is down
- LSB steganography
