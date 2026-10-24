# raica-pysandbox — the image `run_python_analysis` runs model-written programs in.
# docs/DESIGN_run_python_analysis.md. Every program is treated as hostile; this image is one layer of several
# (gVisor runtime, no network, no host mounts, read-only root, nobody user, caps dropped — set by the runner on the
# host, utils/py_sandbox.py, not here). Base pinned by digest, libraries pinned to RAICA's own versions.
# Rebuild: docker build -t raica-pysandbox:1 deploy/pysandbox
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

RUN pip install --no-cache-dir numpy==2.3.2 scipy==1.16.1 matplotlib==3.10.3 sympy==1.14.0 pandas==2.3.1 \
 && MPLCONFIGDIR=/opt/mplcache python -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; plt.figure()" \
 && chmod -R a+rX /opt/mplcache \
 && pip uninstall -y pip setuptools wheel \
 && rm -rf /root/.cache /usr/local/lib/python3.12/ensurepip

COPY runner.py /sandbox/runner.py

ENV MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python3", "-I", "/sandbox/runner.py"]
