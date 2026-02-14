FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY deal_command_center/ deal_command_center/
COPY templates/ templates/
COPY static/ static/
COPY deals/ deals/
COPY run_web.py .

# Create output directory
RUN mkdir -p output avoma_cache

EXPOSE 5000

# Run with gunicorn in production
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "deal_command_center.web:create_app()"]
