# Worker Rules

Workers are reusable processing modules like recipes.

Use workers for:
- OpenCV
- FFmpeg
- telemetry analysis
- anomaly detection
- protocol decoding
- metadata extraction
- compression
- local ML inference

Workers must declare:
- runtime
- inputs
- outputs
- permissions
- resource cost
- sandbox preference

Heavy workers must run through a job queue, not inline with hub requests.
