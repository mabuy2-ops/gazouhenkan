from flask import Flask, request, send_file, render_template, Response
from PIL import Image
import io
import traceback
from datetime import datetime

app = Flask(__name__)

MAX_SVG_SIZE = 512  # Render無料枠(512MB RAM)に合わせて縮小

# ---- SVG 変換 (Pillow のみ、外部バイナリ不要) ----

def _scanline_rects(pixels, w, h, match_val, color_hex):
    """指定インデックス/値のピクセルをRLEで<rect>要素に変換"""
    parts = []
    for y in range(h):
        row_start = y * w
        x = 0
        while x < w:
            if pixels[row_start + x] == match_val:
                sx = x
                while x < w and pixels[row_start + x] == match_val:
                    x += 1
                parts.append(f'<rect x="{sx}" y="{y}" width="{x - sx}" height="1" fill="{color_hex}"/>')
            else:
                x += 1
    return parts

def _convert_to_svg(img, colormode='color', num_colors=8):
    """PIL Image を SVG 文字列に変換（Pillow のみ）"""
    w, h = img.size

    if colormode == 'binary':
        gray = img.convert('L').point(lambda p: 0 if p < 128 else 255)
        pixels = list(gray.getdata())
        rects = _scanline_rects(pixels, w, h, 0, 'black')
        body = '\n'.join(rects)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="white"/>'
            f'{body}'
            f'</svg>'
        )
    else:
        quantized = img.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()
        pixels = list(quantized.getdata())
        used_indices = sorted(set(pixels))

        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        ]
        for idx in used_indices:
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]
            color_hex = f'#{r:02x}{g:02x}{b:02x}'
            parts.extend(_scanline_rects(pixels, w, h, idx, color_hex))
        parts.append('</svg>')
        return '\n'.join(parts)

# ---- routes ----

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/healthz')
def healthz():
    return 'OK flask=running'

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
