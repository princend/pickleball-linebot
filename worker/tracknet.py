"""TrackNetV3 深度學習球體軌跡追蹤封裝。"""
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple


def _run_tracknet_v3_safe(video_path: Path, pred_dir: Path) -> Tuple[Dict[int, Tuple[int, int, int]], Optional[str]]:
    """以相容 CPU / GPU 的方式執行 TrackNetV3 + InpaintNet。

    回傳 (逐幀座標字典, 錯誤訊息)。執行失敗時一定會回傳錯誤訊息 (不再默默吞掉)，由呼叫端決定如何處理。
    注意：預訓練權重 (qaz812345) 是羽球資料訓練，對匹克球的召回率有限。
    """
    import pandas as pd

    wrapper_script = pred_dir / "run_tracknet_wrapper.py"
    wrapper_code = """
import sys
import runpy
import torch

_orig_load = torch.load
def _safe_load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    if not torch.cuda.is_available():
        kwargs["map_location"] = torch.device("cpu")
    return _orig_load(*args, **kwargs)

torch.load = _safe_load
if not torch.cuda.is_available():
    torch.set_num_threads(4)
    torch.Tensor.cuda = lambda self, *a, **kw: self
    torch.nn.Module.cuda = lambda self, *a, **kw: self

sys.path.insert(0, "/opt/TrackNetV3")
sys.argv = [
    "/opt/TrackNetV3/predict.py",
    "--video_file", sys.argv[1],
    "--tracknet_file", "/opt/TrackNetV3/ckpts/TrackNet_best.pt",
    "--inpaintnet_file", "/opt/TrackNetV3/ckpts/InpaintNet_best.pt",
    "--save_dir", sys.argv[2],
    "--batch_size", "4",
]
runpy.run_path("/opt/TrackNetV3/predict.py", run_name="__main__")
"""
    wrapper_script.write_text(wrapper_code, encoding="utf-8")
    proc = subprocess.run(
        ["python", str(wrapper_script), str(video_path), str(pred_dir)],
        cwd="/opt/TrackNetV3",
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        lines = [ln.strip() for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
        last_line = lines[-1] if lines else "unknown error"
        msg = f"TrackNetV3 執行失敗 (exit {proc.returncode}): {last_line[:120]}"
        print(msg)
        return {}, msg

    csv_path = pred_dir / f"{video_path.stem}_ball.csv"
    if not csv_path.exists():
        msg = "TrackNetV3 沒有產出 *_ball.csv"
        print(msg)
        return {}, msg

    df = pd.read_csv(csv_path)
    tracknet_coords: Dict[int, Tuple[int, int, int]] = {}
    for _, row in df.iterrows():
        tracknet_coords[int(row["Frame"])] = (int(row["X"]), int(row["Y"]), int(row["Visibility"]))
    return tracknet_coords, None
