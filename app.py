from flask import Flask, request, send_file, render_template, Response
from PIL import Image
import io
import math
import traceback
from datetime import datetime

app = Flask(__name__)

MAX_SVG_SIZE = 512

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
        import vtracer

        mode = request.form.get('mode', 'color')
        colors = max(2, min(256, int(request.form.get('colors', 16))))
        filter_speckle = max(1, min(100, int(request.form.get('filter_speckle', 4))))
        corner_threshold = max(1, min(180, int(request.form.get('corner_threshold', 60))))
        length_threshold = max(1.0, min(10.0, float(request.form.get('length_threshold', 4.0))))
        splice_threshold = max(1, min(180, int(request.form.get('splice_threshold', 45))))
        path_mode = request.form.get('path_mode', 'spline')
        if path_mode not in ('spline', 'polygon', 'none'):
            path_mode = 'spline'

        img = Image.open(file.stream).convert('RGB')
        w, h = img.size
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
            color_precision=color_precision,
            filter_speckle=filter_speckle,
            corner_threshold=corner_threshold,
            length_threshold=length_threshold,
            splice_threshold=splice_threshold,
            mode=path_mode,
        )

        return Response(svg_str, mimetype='image/svg+xml')

    except Exception:
        return f'変換エラー: {traceback.format_exc()}', 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
