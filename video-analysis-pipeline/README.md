# Video Frame Segment Analysis Pipeline

Downloads a YouTube video, splits it into 5-minute segments, extracts frames and
analyses each segment with the DeepSeek vision model, then merges the results.

## Why DeepSeek

`deepseek-flash` accepts images through an OpenAI-compatible endpoint and caps
each image at **1024 tokens** regardless of its pixel size, so the cost per run
is predictable. Verified against
https://api-docs.deepseek.com/guides/vision/

## Quick start

```bash
cp .env.example .env      # add DEEPSEEK_API_KEY
docker build -t video-analyzer .
docker run --rm -it --env-file .env -v "$PWD/data:/data" video-analyzer run \
  --url "https://www.youtube.com/watch?v=EXAMPLE" --parallel 3
```

## Output

```
data/runs/<run_id>/final.md
data/runs/<run_id>/final.json
data/runs/<run_id>/run_manifest.json
```