# app.py (barcode only + UI at "/")
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
import io, re
from pathlib import Path
import barcode
from barcode.writer import ImageWriter
from PIL import Image

app = FastAPI(title="Barcode API", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent
BARCODE_DIR = BASE_DIR / "generated" / "barcodes"
BARCODE_DIR.mkdir(parents=True, exist_ok=True)

# Templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def sanitize(name: str) -> str:
    s = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_')
    return s or "code"

def unique_path(dirpath: Path, base_name: str, ext: str = ".png") -> Path:
    p = dirpath / f"{base_name}{ext}"
    if not p.exists():
        return p
    i = 1
    while True:
        alt = dirpath / f"{base_name}-{i}{ext}"
        if not alt.exists():
            return alt
        i += 1

@app.get("/")
def home(request: Request):
    # Serves templates/index.html
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/barcode")
def generate_barcode(data: str = Query(..., min_length=1, max_length=1024)):
    try:
        cls = barcode.get_barcode_class('code128')
        bc = cls(data, writer=ImageWriter())
        pil_img: Image.Image = bc.render()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    fname_base = sanitize(data)
    save_path = unique_path(BARCODE_DIR, fname_base, ".png")
    pil_img.save(save_path, format="PNG")
    print(f"Saved barcode -> {save_path}")

    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename=\"{save_path.name}\"'}
    )
