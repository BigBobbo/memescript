"""Restyle Google 3D render tiles with the isometric-nyc model on fal.ai.

Usage (from this directory):
    ../../../.venv/bin/python stylize.py out_nyc45 --tiles 0,0 0,1 0,2 1,0 1,1 1,2

Needs `fal-client` in the venv and FAL_KEY in the environment or in ./.env
(gitignored; never commit it). Each tile is a paid request: about $0.037 for a
1024 x 1024 tile at $0.035 per megapixel.

Model: fal-ai/qwen-image-edit-2511/lora with Andy Coenen's LoRA
`cannoneyed-dark-copper-flea` (isometric-nyc, trained on the original
Qwen-Image-Edit; 2511 shares its architecture). Input format follows his
masked-infill training data: the region to paint carries the raw render inside
a 2 px red border, and the prompt asks for it to be filled in his style. A tile
with no painted neighbours is all render with the border at its edge.

Writes OUTDIR/styled/r<row>_c<col>.png plus a .json with the request ID, seed
and parameters, and OUTDIR/styled/sheet.jpg comparing render and result.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ENDPOINT = "fal-ai/qwen-image-edit-2511/lora"  # 2509-lora returned 500s for every request, Nov 2026
LORA = ("https://hub.oxen.ai/api/repos/cannoneyed/isometric-nyc-v02/file/"
        "55b9eaff9e93ceae2549c85ba2f10b4f/models/cannoneyed-dark-copper-flea/model.safetensors")
PROMPT = ("Fill in the outlined section with the missing pixels corresponding to the "
          "<isometric nyc pixel art> style, removing the border and exactly following the "
          "shape/style/structure of the surrounding image (if present).")
TILE = 1024
BORDER = 2


def load_env(path: Path) -> None:
    """Read FAL_KEY from a dotenv file without echoing it; the environment wins."""
    if os.environ.get("FAL_KEY") or not path.exists():
        return
    for line in path.read_text().splitlines():
        m = re.match(r"""^\s*FAL_KEY\s*=\s*(['"]?)(.*)\1\s*$""", line)
        if m:
            os.environ["FAL_KEY"] = m.group(2)
            return


def template(render: Image.Image, row: int, col: int) -> Image.Image:
    """One tile of render with the red infill border drawn at its edge."""
    box = (col * TILE, row * TILE, (col + 1) * TILE, (row + 1) * TILE)
    if box[2] > render.width or box[3] > render.height:
        raise SystemExit(f"tile {row},{col} runs off the {render.size} render")
    tile = render.crop(box).convert("RGB")
    d = ImageDraw.Draw(tile)
    for i in range(BORDER):
        d.rectangle([i, i, TILE - 1 - i, TILE - 1 - i], outline=(255, 0, 0))
    return tile


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--tiles", nargs="+", default=["0,0"], help="row,col of 1024 px tiles")
    ap.add_argument("--steps", type=int, default=14, help="author's server default")
    ap.add_argument("--cfg", type=float, default=2.0, help="author's true_cfg_scale default")
    ap.add_argument("--lora", default=LORA,
                    help="LoRA URL; fal may fail to pull the Oxen copy, so a fal-storage "
                         "re-upload of the same file also works")
    ap.add_argument("--lora-scale", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=2157)
    ap.add_argument("--force", action="store_true", help="re-run tiles that already have output")
    args = ap.parse_args()

    load_env(HERE / ".env")
    if not os.environ.get("FAL_KEY"):
        print("FAL_KEY is not set (environment or ./.env)", file=sys.stderr)
        return 1
    import fal_client
    import httpx

    out = args.outdir if args.outdir.is_absolute() else HERE / args.outdir
    render = Image.open(out / "limerick_iso_full.png")
    styled = out / "styled"
    styled.mkdir(exist_ok=True)

    done = []
    for spec in args.tiles:
        row, col = (int(v) for v in spec.split(","))
        name = f"r{row}_c{col}"
        if (styled / f"{name}.png").exists() and not args.force:
            print(f"{name}: already done")
            done.append((row, col))
            continue
        src = template(render, row, col)
        src_path = styled / f"{name}_input.png"
        src.save(src_path)

        image_url = fal_client.upload_file(str(src_path))
        arguments = {
            "prompt": PROMPT,
            "image_urls": [image_url],
            "loras": [{"path": args.lora, "scale": args.lora_scale}],
            "num_inference_steps": args.steps,
            "guidance_scale": args.cfg,
            "seed": args.seed,
            "num_images": 1,
            "output_format": "png",
            "acceleration": "none",
        }
        t0 = time.time()
        # Submit once and keep the request ID; a resubmit is a second billed job.
        handle = fal_client.submit(ENDPOINT, arguments=arguments)
        meta = {"endpoint": ENDPOINT, "request_id": handle.request_id, "tile": [row, col],
                **{k: v for k, v in arguments.items() if k != "image_urls"}}
        (styled / f"{name}.json").write_text(json.dumps(meta, indent=2))
        print(f"{name}: submitted {handle.request_id}")
        try:
            result = handle.get()
        except Exception as exc:  # keep the request ID on disk for a status check
            print(f"{name}: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        img = result["images"][0]
        url = img["url"]
        if not url.startswith(("https://v3.fal.media/", "https://fal.media/",
                               "https://v3b.fal.media/", "https://storage.googleapis.com/")):
            print(f"{name}: unexpected result host {url.split('/')[2]}", file=sys.stderr)
            continue
        (styled / f"{name}.png").write_bytes(httpx.get(url, timeout=120).content)
        meta.update(seed=result.get("seed"), result_url=url, seconds=round(time.time() - t0, 1),
                    nsfw=result.get("has_nsfw_concepts"))
        (styled / f"{name}.json").write_text(json.dumps(meta, indent=2))
        print(f"{name}: done in {meta['seconds']} s")
        done.append((row, col))

    if done:
        rows = sorted({r for r, _ in done})
        cols = sorted({c for _, c in done})
        half = TILE // 2
        sheet = Image.new("RGB", (len(cols) * half * 2 + 8, len(rows) * half + 8 * (len(rows) - 1)),
                          "white")
        for r, c in done:
            y = rows.index(r) * (half + 8)
            x = cols.index(c) * half
            a = render.crop((c * TILE, r * TILE, (c + 1) * TILE, (r + 1) * TILE)).convert("RGB")
            b = Image.open(styled / f"r{r}_c{c}.png").convert("RGB")
            sheet.paste(a.resize((half, half)), (x, y))
            sheet.paste(b.resize((half, half)), (len(cols) * half + 8 + x, y))
        sheet.save(styled / "sheet.jpg", quality=90)
        print("wrote", styled / "sheet.jpg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
