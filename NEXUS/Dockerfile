# Dockerfile
# --- Etapa 1: Builder ---
    FROM python:3.10-slim-buster AS builder

    ENV PYTHONDONTWRITEBYTECODE 1
    ENV PYTHONUNBUFFERED 1
    
    # CORRECCIÓN 1: Cambiar los repositorios de Debian a los archivos históricos
    RUN echo "deb http://archive.debian.org/debian/ buster main" > /etc/apt/sources.list && \
        echo "deb http://archive.debian.org/debian-security buster/updates main" >> /etc/apt/sources.list && \
        echo "deb http://archive.debian.org/debian/ buster-updates main" >> /etc/apt/sources.list
    
    # CORRECCIÓN 2: Añadir libgmp-dev para la compilación de fastecdsa
    RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgmp-dev \
        && rm -rf /var/lib/apt/lists/*
    
    # Crear y activar un entorno virtual
    RUN python -m venv /opt/venv
    ENV PATH="/opt/venv/bin:$PATH"
    
    # Instalar dependencias de Python
    WORKDIR /app
    COPY requirements.txt .
    RUN pip install --no-cache-dir --upgrade pip && \
        pip install --no-cache-dir -r requirements.txt
    
    # --- Etapa 2: Final ---
    FROM python:3.10-slim-buster AS final
    
    # Crear un usuario no-root para mejorar la seguridad
    RUN groupadd -r nexus && useradd --no-log-init -r -g nexus nexus
    WORKDIR /home/nexus/app
    
    # Copiar el entorno virtual con las dependencias desde la etapa 'builder'
    COPY --from=builder /opt/venv /opt/venv
    
    # Copiar el código de la aplicación
    COPY --chown=nexus:nexus . .
    
    # Establecer el usuario no-root
    USER nexus
    
    # Exponer el puerto de la API
    EXPOSE 8000
    
    # Activar el entorno virtual y definir el comando de inicio
    ENV PATH="/opt/venv/bin:$PATH"
    CMD ["uvicorn", "nexus.api.core.api_server:app", "--host", "0.0.0.0", "--port", "8000"]