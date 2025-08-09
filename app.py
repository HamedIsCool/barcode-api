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

# Server-side validation pattern:
# (I|C)-SERIES(uppercase letters, 1+)-NUMBER(1+ digits)/YY(two digits)
CODE_PATTERN = re.compile(r'^(I|C)-[A-Z]+-\d+/\d{2}$')

def sanitize(name: str) -> str:
    """Make a filesystem-safe base filename based on the input code."""
    s = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_')
    return s or "code"

def unique_path(dirpath: Path, base_name: str, ext: str = ".png") -> Path:
    """Return a unique path: base.png, base-1.png, base-2.png, ..."""
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
def generate_barcode(
    data: str = Query(..., min_length=1, max_length=1024),
    disposition: str = Query("attachment", pattern="^(inline|attachment)$")  # inline = preview, attachment = download
):
    # Normalize to uppercase (matches frontend behavior)
    data = data.upper().strip()

    # Backend validation to keep inputs clean even from direct API calls
    if not CODE_PATTERN.match(data):
        raise HTTPException(
            status_code=400,
            detail="Invalid code format. Expected (I|C)-[A-Z]+-<number>/<yy>, e.g. I-MCE-169369/25"
        )

    try:
        cls = barcode.get_barcode_class('code128')
        bc = cls(data, writer=ImageWriter())
        pil_img: Image.Image = bc.render()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Save to disk (named after sanitized input, unique if exists)
    fname_base = sanitize(data)
    save_path = unique_path(BARCODE_DIR, fname_base, ".png")
    pil_img.save(save_path, format="PNG")
    print(f"Saved barcode -> {save_path}")

    # Stream back to caller (inline for preview, attachment for download)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Content-Disposition": f'{disposition}; filename="{save_path.name}"'}
    )
