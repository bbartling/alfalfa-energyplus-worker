FROM ubuntu:24.04
ARG EPLUS_URL=https://github.com/NatLabRockies/EnergyPlus/releases/download/v26.1.0/EnergyPlus-26.1.0-6f2e40d102-Linux-Ubuntu24.04-x86_64.tar.gz
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates curl libgomp1 && rm -rf /var/lib/apt/lists/*
RUN mkdir /opt/eplus && curl -fL "$EPLUS_URL" | tar -xz --strip-components=1 -C /opt/eplus
RUN apt-get update && apt-get install -y --no-install-recommends libx11-6 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:/opt/eplus:$PATH"
WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
COPY app app
COPY tests tests
COPY examples examples
CMD ["uvicorn", "app.server:api", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
