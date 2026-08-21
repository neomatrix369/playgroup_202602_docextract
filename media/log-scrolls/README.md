# Log scroll captures

Drop raw log / `.output` files into **`inputs/`**, then render:

```bash
python utility/render_log_scroll.py media/log-scrolls/inputs/your-file.output
```

Defaults: **120s** MP4, **~10 lines** visible. Behaves like `tail -f` (fixed
viewport; new lines append at the bottom and push older lines up).

```bash
# Faster / taller viewport (common share clip)
python utility/render_log_scroll.py media/log-scrolls/inputs/your-file.output \
  --duration 60 --visible-lines 18

# Optional GIF (often very large for full 2 min — prefer MP4)
python utility/render_log_scroll.py media/log-scrolls/inputs/your-file.output --gif
```

Outputs go to **`outputs/`** (gitignored — large binaries).
