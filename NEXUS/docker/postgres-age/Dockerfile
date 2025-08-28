FROM postgres:15

# Install dependencies
RUN apt-get update && apt-get install -y \
    bison \
    postgresql-server-dev-15 \
    build-essential \
    git \
    cmake \
    flex \
    perl \
    clang-19 \
    && git clone https://github.com/apache/age.git \
    && cd age \
    && git checkout release/PG15/1.4.0 \
    && make install

# Configure extensions
RUN echo "shared_preload_libraries = 'age'" >> /usr/share/postgresql/postgresql.conf.sample

# Initialization script
COPY init-age.sh /docker-entrypoint-initdb.d/
RUN chmod +x /docker-entrypoint-initdb.d/init-age.sh

EXPOSE 5432