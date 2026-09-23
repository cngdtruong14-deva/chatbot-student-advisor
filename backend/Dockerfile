FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-vie \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.lock ./
RUN pip install -r requirements.lock
RUN pip install pytesseract==0.3.13 pdf2image==1.17.0 Pillow==11.1.0
RUN pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install chromadb==1.3.5 sentence-transformers==5.1.2 transformers==4.57.1
COPY packages/advisor_core /packages/advisor_core
RUN pip install --no-deps /packages/advisor_core && useradd --uid 10001 --create-home advisor
COPY backend/ /app/
COPY contracts /contracts
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
