FROM python:3.13-slim

# Install System Dependencies
RUN apt-get update && apt-get install -y \
    nginx \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Hugo Extended
ARG HUGO_VER="0.152.2"
RUN curl -L "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VER}/hugo_extended_${HUGO_VER}_linux-amd64.deb" -o hugo.deb \
    && dpkg -i hugo.deb \
    && rm hugo.deb

# Python Setup
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create Non-Root User
RUN useradd -m -u 1000 toast

# Configuration Setup
RUN rm /etc/nginx/sites-enabled/default
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy LocalToast Source
COPY . /app
RUN chmod +x /app/entrypoint.sh

# Prepare Directories
RUN mkdir -p /app/site/content/recipes /app/site/public /var/log/supervisor /var/run/supervisor /var/run/nginx \
    && chown -R toast:toast /app \
    && chown -R toast:toast /var/log/nginx \
    && chown -R toast:toast /var/lib/nginx \
    && chown -R toast:toast /var/log/supervisor \
    && chown -R toast:toast /var/run/supervisor \
    && chown -R toast:toast /var/run/nginx

# Switch to Non-Root User
USER toast

# Start via Entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]