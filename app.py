from flask import Flask, request, send_file, render_template, Response
from PIL import Image
import io
import math
import traceback
from datetime import datetime

app = Flask(__name__)

MAX_SVG_SIZE = 512  # Render無料枠(512MB RAM)に合わせて縮小

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/healthz')
def healthz():
    """診断用: 起動確認（重いライブラリは読み込まない）"""
    return 'OK flask=running'

@app.route('/healthz/vtracer')
def healthz_vtracer():
    """診断用: vtracer動作確認"""
    try:
        import vtracer
        img = Image.new('RGB', (4, 4), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        svg = vtracer.convert_raw_image_to_svg(buf.getvalue(), img_format='png', colormode='color')
        return f'OK vtracer={vtracer.__version__ if hasattr(vtracer, "__version__") else "installed"} svg_len={len(svg)}'
    except Exception as e:
        return f'ERROR: {traceback.format_exc()}', 500

@app.route('/healthz/rembg')
def healthz_rembg():
    """診断用: rembg動作確認"""
    try:
        from rembg import remove
        return 'OK rembg=installed'
    except Exception as e:
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
    except Exception as e:
        return f'背景除去エラー: {traceback.format_exc()}', 500

@app.route('/convert/svg', methods=['POST'])
def convert_svg():
    file = request.files.get('file')
    if not file:
        return '画像ファイルが選択されていません', 400

    try:
        import vtracer

        mode = request.form.get('mode', 'color')
        colors = int(request.form.get('colors', 8))

        img = Image.open(file.stream).convert('RGB')
        w, h = img.size

        # メモリ節約のため長辺512px以下にリサイズ
        if max(w, h) > MAX_SVG_SIZE:
            scale = MAX_SVG_SIZE / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='PNG')
        img_bytes = buf.getvalue()
        buf.close()

        colormode = 'binary' if mode == 'bw' else 'color'
        color_precision = 1 if mode == 'bw' else max(1, min(8, round(math.log2(max(2, colors)))))

        svg_str = vtracer.convert_raw_image_to_svg(
            img_bytes,
            img_format='png',
            colormode=colormode,
            color_precision=color_precision
        )

        return Response(svg_str, mimetype='image/svg+xml')

    except Exception as e:
        return f'変換エラー: {traceback.format_exc()}', 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
