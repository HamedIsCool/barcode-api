# app.py (barcode only + UI at "/")
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse
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
    return templates.TemplateResponse("index.html", {"request": request})

def _make_barcode_bytes(data: str) -> tuple[bytes, str]:
    """Validate, render, save, and return (png_bytes, filename)."""
    data = data.upper().strip()
    if not CODE_PATTERN.match(data):
        raise HTTPException(
            status_code=400,
            detail="Invalid code format. Expected (I|C)-[A-Z]+-<number>/<yy>, e.g. I-MCE-169369/25"
        )

    cls = barcode.get_barcode_class('code128')
    bc = cls(data, writer=ImageWriter())
    pil_img: Image.Image = bc.render()

    fname_base = sanitize(data)
    save_path = unique_path(BARCODE_DIR, fname_base, ".png")
    pil_img.save(save_path, format="PNG")
    print(f"Saved barcode -> {save_path}")

    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue(), save_path.name

# Preview (inline)
@app.get("/barcode/preview")
def barcode_preview(data: str = Query(..., min_length=1, max_length=1024)):
    content, fname = _make_barcode_bytes(data)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{fname}"'}
    )

# Download (Save As)
@app.get("/barcode/download")
def barcode_download(data: str = Query(..., min_length=1, max_length=1024)):
    content, fname = _make_barcode_bytes(data)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )

# Dedicated print page (auto-print after image loads)
@app.get("/print", response_class=HTMLResponse)
def print_page(data: str = Query(..., min_length=1, max_length=1024)):
    data = data.upper().strip()
    return f"""
<!doctype html>
<html lang="az">
<head>
  <meta charset="utf-8" />
  <title>Çap – {data}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    html, body {{ margin:0; padding:0; }}
    .wrap {{ display:flex; align-items:center; justify-content:center; min-height:100vh; }}
    .label {{ width:80mm; height:40mm; display:flex; align-items:center; justify-content:center; background:#fff; }}
    .label img {{ display:block; max-width:100%; max-height:100%; object-fit:contain; image-rendering:crisp-edges; }}
    @media print {{
      @page {{ size: 80mm 40mm; margin: 0; }}
      html, body {{ margin:0 !important; padding:0 !important; }}
      .wrap {{ min-height:auto; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="label">
      <img id="img" alt="barcode" src="/barcode/preview?data={data}&t={{int(__import__('time').time()*1000)}}" />
    </div>
  </div>
  <script>
    const img = document.getElementById('img');
    function printNow() {{ setTimeout(() => window.print(), 100); }}
    if (img.complete) printNow(); else img.addEventListener('load', printNow);
  </script>
</body>
</html>
"""
