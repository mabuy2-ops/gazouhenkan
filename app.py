from flask import Flask, request, send_file, render_template, Response
from PIL import Image
from rembg import remove
import io
from datetime import datetime
import vtracer

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

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

    input_data = file.stream.read()
    output_data = remove(input_data)

    output = io.BytesIO(output_data)
    base_name = file.filename.rsplit('.', 1)[0]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(output, mimetype='image/png',
                     as_attachment=True, download_name=f'{base_name}_nobg_{timestamp}.png')

@app.route('/convert/svg', methods=['POST'])
def convert_svg():
    file = request.files.get('file')
    if not file:
        return '画像ファイルが選択されていません', 400

    mode = request.form.get('mode', 'color')
    colors = int(request.form.get('colors', 8))

    img_bytes = file.stream.read()
    ext = file.filename.rsplit('.', 1)[-1].lower()
    img_format = 'jpg' if ext in ('jpg', 'jpeg') else 'png'

    colormode = 'binary' if mode == 'bw' else 'color'
    # color_precision: 1-8 bits per channel (2^n colors per channel)
    # map user's color count (2-64) to precision (1-6)
    import math
    color_precision = 1 if mode == 'bw' else max(1, min(8, round(math.log2(max(2, colors)))))

    svg_str = vtracer.convert_raw_image_to_svg(
        img_bytes,
        img_format=img_format,
        colormode=colormode,
        color_precision=color_precision
    )

    return Response(svg_str, mimetype='image/svg+xml')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
