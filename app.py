from flask import Flask, request, send_file, render_template, Response
from PIL import Image
import io
import re
import subprocess
import traceback
from datetime import datetime

app = Flask(__name__)

MAX_SVG_SIZE = 512  # Render無料枠(512MB RAM)に合わせて縮小

# ---- potrace helpers ----

def _img_to_pbm(img_gray):
    """PIL グレースケール画像を PBM(P4) バイト列に変換"""
    w, h = img_gray.size
    pixels = list(img_gray.getdata())
    header = f"P4\n{w} {h}\n".encode()
    row_bytes = (w + 7) // 8
    data = bytearray(h * row_bytes)
    for y in range(h):
        for x in range(w):
            if pixels[y * w + x] < 128:
                data[y * row_bytes + x // 8] |= (1 << (7 - x % 8))
    return header + bytes(data)

def _run_potrace(pbm_data, fill_color):
    """potrace を実行して SVG path 要素文字列を返す"""
    result = subprocess.run(
        ['potrace', '-s', '-o', '-', '-'],
        input=pbm_data,
        capture_output=True,
        timeout=30
    )
    svg = result.stdout.decode('utf-8', errors='replace')
    paths = re.findall(r'<path\b[^>]*\bd="([^"]+)"', svg)
    if not paths:
        return ''
    if isinstance(fill_color, tuple):
        color_hex = '#{:02x}{:02x}{:02x}'.format(*fill_color)
    else:
        color_hex = fill_color
    return '\n'.join(f'<path d="{d}" fill="{color_hex}"/>' for d in paths)

def _convert_to_svg(img, colormode='color', num_colors=8):
    """PIL Image を SVG 文字列に変換"""
    w, h = img.size

    if colormode == 'binary':
        gray = img.convert('L')
        pbm = _img_to_pbm(gray)
        paths_svg = _run_potrace(pbm, 'black')
        return (
            f'<?xml version="1.0"?>'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="white"/>'
            f'{paths_svg}'
            f'</svg>'
        )
    else:
        quantized = img.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()
        pixels = list(quantized.getdata())
        used_indices = sorted(set(pixels))

        svg_parts = [
            f'<?xml version="1.0"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        ]
        for idx in used_indices:
            r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
            mask = Image.new('L', (w, h), 255)
            mask.putdata([0 if p == idx else 255 for p in pixels])
            pbm = _img_to_pbm(mask)
            paths = _run_potrace(pbm, (r, g, b))
            if paths:
                svg_parts.append(paths)
        svg_parts.append('</svg>')
        return '\n'.join(svg_parts)

# ---- routes ----

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/healthz')
def healthz():
    return 'OK flask=running'

@app.route('/healthz/potrace')
def healthz_potrace():
    """診断用: potrace動作確認"""
    try:
        img = Image.new('L', (8, 8), 128)
        pbm = _img_to_pbm(img)
        result = subprocess.run(['potrace', '-s', '-o', '-', '-'],
                                input=pbm, capture_output=True, timeout=10)
        return f'OK potrace returncode={result.returncode} svg_len={len(result.stdout)}'
    except Exception:
        return f'ERROR: {traceback.format_exc()}', 500

@app.route('/healthz/rembg')
def healthz_rembg():
    """診断用: rembg動作確認"""
    try:
        from rembg import remove
        return 'OK rembg=installed'
    except Exception:
        return f'ERROR: {traceback.format_exc()}', 500

@app.route('/convert/webp', methods=['POST'])
def convert_webp():
    file = request.files.get('file')
    if not file:
        return '画像ファイルが選択されていません', 400

    img = Image.open(file.stream).convert('RGB')
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=95)
    output.seek(0)

    base_name = file.filename.rsplit('.', 1)[0]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(output, mimetype='image/jpeg',
                     as_attachment=True, download_name=f'{base_name}_{timestamp}.jpg')

@app.route('/convert/bg', methods=['POST'])
def remove_bg():
    file = request.files.get('file')
    if not file:
        return '画像ファイルが選択されていません', 400

    try:
        from rembg import remove
        input_data = file.stream.read()
        output_data = remove(input_data)
        output = io.BytesIO(output_data)
        base_name = file.filename.rsplit('.', 1)[0]
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return send_file(output, mimetype='image/png',
                         as_attachment=True, download_name=f'{base_name}_nobg_{timestamp}.png')
    except Exception:
        return f'背景除去エラー: {traceback.format_exc()}', 500

@app.route('/convert/svg', methods=['POST'])
def convert_svg():
    file = request.files.get('file')
    if not file:
        return '画像ファイルが選択されていません', 400

    try:
        mode = request.form.get('mode', 'color')
        colors = max(2, min(256, int(request.form.get('colors', 8))))

        img = Image.open(file.stream).convert('RGB')
        w, h = img.size

        if max(w, h) > MAX_SVG_SIZE:
            scale = MAX_SVG_SIZE / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        colormode = 'binary' if mode == 'bw' else 'color'
        svg_str = _convert_to_svg(img, colormode=colormode, num_colors=colors)

        return Response(svg_str, mimetype='image/svg+xml')

    except Exception:
        return f'変換エラー: {traceback.format_exc()}', 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
