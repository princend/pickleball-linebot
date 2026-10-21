"""YOLO26 + ByteTrack 球員偵測與站位反投影。"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_worker_dir = Path(__file__).resolve().parent
_repo_root = _worker_dir.parent
for _p in [str(_repo_root), str(_worker_dir)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from worker.camera import CameraModel
    from worker.constants import YOLO_WEIGHTS_DIR, YOLO_WEIGHTS_NAME
except ImportError:
    from camera import CameraModel
    from constants import YOLO_WEIGHTS_DIR, YOLO_WEIGHTS_NAME


def _detect_players_yolo(
    video_path: Path,
    cam: CameraModel,
    n_frames: int,
) -> Tuple[Dict[int, Tuple[int, int, int, int, float, Tuple[float, float]]], Optional[str]]:
    """YOLO26 + ByteTrack 偵測擊球者。選「累計面積最大的軌跡 ID」(離鏡頭最近的人)，其餘幀以線性內插補齊框。

    框與信心值皆為模型輸出；腳點取框底中點，經相機模型投影到球場座標。回傳 (player_info, 錯誤訊息)。
    """
    import numpy as np

    try:
        from ultralytics import YOLO

        weights = Path(YOLO_WEIGHTS_DIR) / YOLO_WEIGHTS_NAME
        model = YOLO(str(weights) if weights.exists() else YOLO_WEIGHTS_NAME)
        stride = int(os.environ.get("YOLO_STRIDE", "2"))
        imgsz = int(os.environ.get("YOLO_IMGSZ", "960"))

        raw: List[Tuple[int, Optional[int], float, float, float, float, float]] = []
        for i, r in enumerate(
            model.track(
                source=str(video_path),
                classes=[0],
                imgsz=imgsz,
                conf=0.3,
                tracker="bytetrack.yaml",
                stream=True,
                verbose=False,
                vid_stride=stride,
            )
        ):
            frame_idx = i * stride
            if r.boxes is None or len(r.boxes) == 0:
                continue
            ids = r.boxes.id.int().tolist() if r.boxes.id is not None else [None] * len(r.boxes)
            for b, tid in zip(r.boxes, ids):
                x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
                raw.append((frame_idx, tid, x1, y1, x2, y2, float(b.conf[0])))
    except Exception as e:  # noqa: BLE001
        msg = f"YOLO26 球員偵測失敗：{e}"
        print(msg)
        return {}, msg

    if not raw:
        return {}, "YOLO26 沒有偵測到任何球員"

    area_by_id: Dict[Any, float] = {}
    for _f, tid, x1, y1, x2, y2, _c in raw:
        area_by_id[tid] = area_by_id.get(tid, 0.0) + (x2 - x1) * (y2 - y1)
    main_id = max(area_by_id, key=lambda k: area_by_id[k])

    per_frame: Dict[int, Tuple[float, float, float, float, float]] = {}
    # 第一輪：每幀取面積最大者 (離鏡頭最近的人)；第二輪：若該幀有主要追蹤 ID 的框則優先採用
    for f, tid, x1, y1, x2, y2, c in raw:
        cur = per_frame.get(f)
        if cur is None or (x2 - x1) * (y2 - y1) > (cur[2] - cur[0]) * (cur[3] - cur[1]):
            per_frame[f] = (x1, y1, x2, y2, c)
    for f, tid, x1, y1, x2, y2, c in raw:
        if tid == main_id:
            per_frame[f] = (x1, y1, x2, y2, c)

    fs = sorted(per_frame)
    arr = np.array([per_frame[f] for f in fs], dtype=float)
    info: Dict[int, Tuple[int, int, int, int, float, Tuple[float, float]]] = {}
    for i in range(n_frames):
        coords = [float(np.interp(i, fs, arr[:, j])) for j in range(4)]
        conf = float(arr[int(np.argmin(np.abs(np.array(fs) - i))), 4])
        x1, y1, x2, y2 = coords
        foot = cam.uv_to_ground(0.5 * (x1 + x2), y2)
        info[i] = (int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)), round(conf, 2), (round(foot[0], 2), round(foot[1], 2)))
    return info, None
