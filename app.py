from flask import Flask, request, send_file, render_template, Response
from PIL import Image, ImageFilter
import io
import traceback
from datetime import datetime
from collections import deque
import numpy as np

app = Flask(__name__)

MAX_SVG_SIZE = 512

# ──────────────────────────────────────────────
# 輪郭トレース / 平滑化 ユーティリティ
# ──────────────────────────────────────────────

def _label_components(mask):
    """BFS で連結成分ラベリング（8近傍）"""
    h, w = mask.shape
    labels = np.where(mask, -1, 0).astype(np.int32)
    current_label = 0
    component_sizes = []

    for seed_r, seed_c in zip(*np.where(labels == -1)):
        seed_r, seed_c = int(seed_r), int(seed_c)
        if labels[seed_r, seed_c] != -1:
            continue
        current_label += 1
        size = 0
        queue = deque([(seed_r, seed_c)])
        labels[seed_r, seed_c] = current_label
        while queue:
            r, c = queue.popleft()
            size += 1
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < h and 0 <= nc < w and labels[nr, nc] == -1:
                        labels[nr, nc] = current_label
                        queue.append((nr, nc))
        component_sizes.append((current_label, size))

    return labels, component_sizes


def _trace_boundary(mask):
    """Moore 境界トレースアルゴリズム"""
    h, w = mask.shape
    filled = np.where(mask)
    if len(filled[0]) == 0:
        return []

    min_row = int(filled[0].min())
    start_c = int(filled[1][filled[0] == min_row].min())
    start_r = min_row

    # 時計回り 8 方向: 0=右,1=右下,2=下,3=左下,4=左,5=左上,6=上,7=右上
    DIRS = [(0,1),(1,1),(1,0),(1,-1),(0,-1),(-1,-1),(-1,0),(-1,1)]

    contour = [(start_c, start_r)]
    r, c = start_r, start_c
    back = 4  # 左から来たと仮定

    for _ in range(w * h * 2 + 10):
        found = False
        for i in range(1, 9):
            d = (back + i) % 8
            nr = r + DIRS[d][0]
            nc = c + DIRS[d][1]
            if 0 <= nr < h and 0 <= nc < w and mask[nr, nc]:
                back = (d + 4) % 8
                r, c = nr, nc
                if r == start_r and c == start_c and len(contour) > 2:
                    return contour
                contour.append((c, r))
                found = True
                break
        if not found:
            break

    return contour


def _rdp(points, epsilon=2.0):
    """Ramer-Douglas-Peucker 折れ線簡略化"""
    if len(points) <= 2:
        return list(points)

    pts = np.array(points, dtype=float)

    def _rdp_rec(pts):
        if len(pts) <= 2:
            return [tuple(pts[0]), tuple(pts[-1])]
        start, end = pts[0], pts[-1]
        line = end - start
        norm = np.linalg.norm(line)
        if norm < 1e-10:
            dists = np.linalg.norm(pts[1:-1] - start, axis=1)
        else:
            dists = np.abs(
                (pts[1:-1, 0] - start[0]) * line[1] -
                (pts[1:-1, 1] - start[1]) * line[0]
            ) / norm
        idx = int(np.argmax(dists))
        if dists[idx] > epsilon:
            left = _rdp_rec(pts[:idx + 2])
            right = _rdp_rec(pts[idx + 1:])
            return left[:-1] + right
        return [tuple(pts[0]), tuple(pts[-1])]

    return _rdp_rec(pts)


def _chaikin(points, iterations=3):
    """Chaikin のコーナーカット（閉じた多角形を平滑化）"""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 3:
        return pts
    if pts[0] != pts[-1]:
        pts.append(pts[0])

    for _ in range(iterations):
        new_pts = []
        n = len(pts) - 1
        for i in range(n):
            p0, p1 = pts[i], pts[i + 1]
            q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
            r = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
            new_pts.extend([q, r])
        new_pts.append(new_pts[0])
        pts = new_pts

    return pts


def _component_to_path(component_mask, epsilon=1.5):
    """1 成分マスク → SVG path d 属性文字列"""
    contour = _trace_boundary(component_mask)
    if len(contour) < 3:
        return None
    simplified = _rdp(contour, epsilon=epsilon)
    smooth = _chaikin(simplified, iterations=3)
    pts = smooth[:-1]  # 閉じる点を除去
    if len(pts) < 3:
        return None
    d = f"M {pts[0][0]:.2f} {pts[0][1]:.2f}"
    for p in pts[1:]:
        d += f" L {p[0]:.2f} {p[1]:.2f}"
    d += " Z"
    return d


def _convert_to_svg(img, colormode='color', num_colors=8):
    w, h = img.size
    # ノイズ低減のため軽くブラー
    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
    ]

    if colormode == 'binary':
        svg_parts.append(f'<rect width="{w}" height="{h}" fill="white"/>')
        binary = np.array(img.convert('L')) < 128
        labels, components = _label_components(binary)
        for label, size in sorted(components, key=lambda x: -x[1]):
            if size < 5:
                continue
            d = _component_to_path(labels == label)
            if d:
                svg_parts.append(f'<path d="{d}" fill="black"/>')

    else:
        quantized = img.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()
        q_array = np.array(quantized, dtype=np.int32)
        used_indices = sorted(set(q_array.flatten().tolist()))

        for idx in used_indices:
            r_val = palette[idx * 3]
            g_val = palette[idx * 3 + 1]
            b_val = palette[idx * 3 + 2]
            color_hex = f'#{r_val:02x}{g_val:02x}{b_val:02x}'

            mask = q_array == idx
            labels, components = _label_components(mask)

            d_list = []
            for label, size in sorted(components, key=lambda x: -x[1]):
                if size < 8:
                    continue
                d = _component_to_path(labels == label)
                if d:
                    d_list.append(d)

            if d_list:
                combined = ' '.join(d_list)
                svg_parts.append(
                    f'<path d="{combined}" fill="{color_hex}" fill-rule="evenodd"/>'
                )

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

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
