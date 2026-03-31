# Demo-grade single-stage build.
#
# Production upgrade path:
#   - Use a multi-stage build: builder stage installs deps, final stage copies
#     only the installed packages (no build tools, no .git, no tests).
#   - Switch base image to python:3.11-slim or distroless for a smaller attack surface.
#   - Run as a non-root user (adduser appuser && USER appuser).
#   - Pin image digest instead of tag for reproducible builds.
#
# Example multi-stage skeleton:
#   FROM python:3.11-slim AS builder
#   RUN pip install --no-cache-dir -r requirements.txt --target /install
#
#   FROM python:3.11-slim
#   COPY --from=builder /install /usr/local/lib/python3.11/site-packages
#   COPY app/ ./app/
#   ...

FROM python:3.11-slim

WORKDIR /app

# Install only production deps — pytest and other dev tools are NOT included.
# requirements.txt is kept separate from requirements-dev.txt intentionally.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads chroma_data data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
