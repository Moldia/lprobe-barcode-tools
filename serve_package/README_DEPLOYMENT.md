# L-probe Barcode Tools deployment

This app is packaged for SciLifeLab Serve Gradio hosting.

## Files

- `app.py`: Gradio app and workflow logic.
- `main.py`: container entrypoint.
- `requirements.txt`: Python dependencies.
- `Dockerfile`: Docker image definition for Serve.
- `.dockerignore`: keeps local notebooks, outputs, and virtual environments out of the image.
- `APP_USER_GUIDE.md`: user-facing workflow, input, output, and Opentrons usage documentation.

## Local Docker build

```bash
docker build --platform linux/amd64 -t lprobe-barcode-tools:v1 .
docker run --rm -it -p 7860:7860 lprobe-barcode-tools:v1
```

Then open:

```text
http://localhost:7860
```

## Publishing

Publish the Docker image to DockerHub or GHCR with a unique tag, then create a Gradio app on SciLifeLab Serve with:

- Port: `7860`
- Image: your public image URL, for example `your-user/lprobe-barcode-tools:v1`
- Permissions: `Link` or `Public`
- Source code URL: the public repository or DOI-backed source archive

SciLifeLab Serve requires app code and image to be publicly available for hosted public apps.
