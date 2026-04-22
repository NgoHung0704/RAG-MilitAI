FROM python:3.11-slim

WORKDIR /app

# Install CPU-only torch first to avoid pulling heavy CUDA packages
# (sentence-transformers depends on torch; without this pip defaults to the GPU build)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app/main.py", "--server.address=0.0.0.0", "--server.port=8501"]
