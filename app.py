# app.py (multi-barcode: preview, download, single print, batch print, one-page grid)
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List, Optional, Tuple
import io, re, time
from pathlib import Path
import barcode
from barcode.writer import ImageWriter
from PIL import Image

app = FastAPI(title="Barcode API", version="1.3.0")

BASE_DIR = Path(__file__).resolve().parent
BARCODE_DIR = BASE_DIR / "generated" / "barcodes"
BARCODE_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# (I|C)-SERIES(uppercase letters, 1+)-NUMBER(1+ digits)/YY(two digits)
CODE_PATTERN = re.compile(r'^(I|C)-[A-Z]+-\d+/\d{2}$')

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

def _validate_code(c: str) -> str:
    cc = (c or "").upper().strip()
    if not CODE_PATTERN.match(cc):
        raise HTTPException(400, detail=f"Invalid code: {cc}")
    return cc

def _make_barcode_bytes(data: str) -> Tuple[bytes, str]:
    data = _validate_code(data)
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

def _parse_codes(code_params: Optional[List[str]], codes_blob: Optional[str]) -> List[str]:
    out: List[str] = []
    if code_params:
        out.extend(code_params)
    if codes_blob:
        # split by comma or newline
        parts = re.split(r'[,\r\n]+', codes_blob)
        out.extend(p for p in parts if p and p.strip())
    if not out:
        raise HTTPException(400, detail="No codes provided. Use ?code=A&code=B or ?codes=A,B or ?codes=lines")
    # validate & normalize
    norm: List[str] = []
    bad: List[str] = []
    for c in out:
        cc = (c or "").upper().strip()
        if not cc:
            continue
        if not CODE_PATTERN.match(cc):
            bad.append(cc)
        else:
            if cc not in norm:
                norm.append(cc)
    if bad:
        raise HTTPException(400, detail=f"Invalid codes: {', '.join(bad)}")
    if not norm:
        raise HTTPException(400, detail="No valid codes after validation.")
    return norm

@app.get("/")
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Single: inline preview (for <img>)
@app.get("/barcode/preview")
def barcode_preview(data: str = Query(..., min_length=1, max_length=1024)):
    content, fname = _make_barcode_bytes(data)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{fname}"'}
    )

# Single: download (Save As)
@app.get("/barcode/download")
def barcode_download(data: str = Query(..., min_length=1, max_length=1024)):
    content, fname = _make_barcode_bytes(data)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )

# Single: dedicated print page (80x40 mm)
@app.get("/print", response_class=HTMLResponse)
def print_page(data: str = Query(..., min_length=1, max_length=1024)):
    code = _validate_code(data)
    ts = int(time.time() * 1000)
    return f"""
<!doctype html>
<html lang="az">
<head>
  <meta charset="utf-8" />
  <title>Çap – {code}</title>
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
      <img id="img" alt="barcode" src="/barcode/preview?data={code}&t={ts}" />
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

# Batch: one label PER PAGE (80x40mm sheets)
@app.get("/print-batch", response_class=HTMLResponse)
def print_batch(
    code: Optional[List[str]] = Query(None),
    codes: Optional[str] = Query(None, description="Comma/newline separated")
):
    codes_list = _parse_codes(code, codes)
    ts = int(time.time() * 1000)
    items_html = "\n".join(
        f'<div class="sheet"><div class="label"><img src="/barcode/preview?data={c}&t={ts}" alt="barcode {c}" /></div></div>'
        for c in codes_list
    )
    return f"""
<!doctype html>
<html lang="az">
<head>
  <meta charset="utf-8" />
  <title>Çap – {len(codes_list)} barkod (hər səhifəyə 1)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {{ margin:0; background:#fff; }}
    .sheet {{ width:80mm; height:40mm; display:flex; align-items:center; justify-content:center; page-break-after: always; }}
    .label {{ width:80mm; height:40mm; display:flex; align-items:center; justify-content:center; background:#fff; }}
    .label img {{ display:block; max-width:100%; max-height:100%; object-fit:contain; image-rendering:crisp-edges; }}
    .note {{ padding:10px; font-size:12px; color:#374151; }}
    @media print {{
      @page {{ size: 80mm 40mm; margin: 0; }}
      .note {{ display:none; }}
    }}
  </style>
</head>
<body>
  <div class="note">Bütün şəkillər yükləndikdən sonra çap pəncərəsi açılacaq…</div>
  {items_html}
  <script>
    const imgs = Array.from(document.images);
    let loaded = 0;
    function maybePrint() {{ if (loaded === imgs.length) setTimeout(() => window.print(), 150); }}
    imgs.forEach(img => {{
      if (img.complete) {{ loaded++; maybePrint(); }}
      else {{
        img.addEventListener('load', () => {{ loaded++; maybePrint(); }});
        img.addEventListener('error', () => {{ loaded++; maybePrint(); }});
      }}
    }});
  </script>
</body>
</html>
"""

# Batch: MANY labels on ONE A4 page (auto-wrap grid)
@app.get("/print-grid", response_class=HTMLResponse)
def print_grid(
    code: Optional[List[str]] = Query(None),
    codes: Optional[str] = Query(None, description="Comma/newline separated")
):
    codes_list = _parse_codes(code, codes)
    ts = int(time.time() * 1000)
    items_html = "\n".join(
        f'<div class="cell"><img src="/barcode/preview?data={c}&t={ts}" alt="barcode {c}" /><div class="cap">{c}</div></div>'
        for c in codes_list
    )
    return f"""
<!doctype html>
<html lang="az">
<head>
  <meta charset="utf-8" />
  <title>Çap – {len(codes_list)} barkod (A4-də bir səhifə)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; }}
    body {{ margin: 10mm; background:#fff; }}
    .grid {{ display:flex; flex-wrap:wrap; gap:10mm 10mm; }}
    .cell {{
      width:80mm; display:flex; flex-direction:column; align-items:center; justify-content:flex-start;
      break-inside: avoid; page-break-inside: avoid;
    }}
    .cell img {{ display:block; max-width:80mm; max-height:40mm; object-fit:contain; image-rendering:crisp-edges; }}
    .cap {{ margin-top:2mm; font-size:10pt; color:#111; word-break:break-word; text-align:center; }}

    .note {{ padding:6px 0 10px; font-size:10pt; color:#374151; }}

    @media print {{
      @page {{ size: A4 portrait; margin: 10mm; }}
      .note {{ display:none; }}
    }}
  </style>
</head>
<body>
  <div class="note">Bütün şəkillər yükləndikdən sonra çap pəncərəsi açılacaq…</div>
  <div class="grid" id="grid">
    {items_html}
  </div>
  <script>
    const imgs = Array.from(document.images);
    let loaded = 0;
    function maybePrint() {{ if (loaded === imgs.length) setTimeout(() => window.print(), 150); }}
    imgs.forEach(img => {{
      if (img.complete) {{ loaded++; maybePrint(); }}
      else {{
        img.addEventListener('load', () => {{ loaded++; maybePrint(); }});
        img.addEventListener('error', () => {{ loaded++; maybePrint(); }});
      }}
    }});
  </script>
</body>
</html>
"""
