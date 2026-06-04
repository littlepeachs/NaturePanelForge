# Demo Videos

This repository stays code-only, so large video files should not be committed. Publish demos as release assets, hosted files, or documentation links.

Recommended short recordings:

1. **Gallery walkthrough**: open `http://166.111.35.177:18081/`, switch domains, filter chart types, and inspect target/reproduced/refined panels.
2. **Single panel to code**: run `forge.py single-panel-image` on one target panel and show `reproduce_panel.py`, rendered PNG/PDF, and `result.json`.
3. **Agent workflow**: show the three stages in the README diagram, then open one panel's review summary and refine complexity assessment.

Suggested recording command with `ffmpeg`:

```bash
ffmpeg -f x11grab -framerate 30 -i "$DISPLAY" \
  -video_size 1920x1080 \
  -c:v libx264 -preset veryfast -crf 23 \
  naturepanelforge_demo.mp4
```

For a browser-only recording, use any screen recorder and export MP4. Keep the video outside the source tree, then link it from the README or a GitHub release.

Suggested README link format:

```markdown
[Watch the gallery walkthrough](https://example.com/naturepanelforge-gallery-demo.mp4)
```
