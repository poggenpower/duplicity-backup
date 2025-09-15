# Stage 1: The Build Stage
# This container is for building the duplicity wheel and other dependencies
# It will be discarded after the build process.

FROM docker.io/python:3.12-alpine AS build

# Install build dependencies
RUN apk fix && \
    apk add --no-cache \
        ca-certificates \
        openssh \
        gpg \
        gpg-agent \
        librsync \
        gettext \
        build-base \
        linux-headers \
        python3-dev \
        librsync-dev \
        git

# Install Python dependencies and duplicity
# We use setuptools_scm for duplicity's build process and dependencies.
# python-gettext is needed for duplicity.
RUN pip install setuptools_scm python-gettext && \
	# install duplicity and its basic dependencies into a wheel directory
	# We build duplicity from source to have more control over the version and dependencies.
	# avoid installing dependencies used for exotic backends only. 
	# CFLAGS is used to suppress a warning during the build process of duplicity
    CFLAGS="-Wno-int-conversion" pip wheel --wheel-dir=/opt/wheels https://gitlab.com/duplicity/duplicity/-/archive/rel.3.0.5.1/duplicity-rel.3.0.5.1.tar.gz?ref_type=tags --no-deps && \
    wget "https://gitlab.com/duplicity/duplicity/-/raw/rel.3.0.5.1/requirements.txt?ref_type=tags&inline=false" -O /opt/duplicity-requirements.txt && \
	sed -n '/##### basic requirements #####/,/##### backend libraries #####/p' /opt/duplicity-requirements.txt > /opt/duplicity-basic-requirements.txt && \
	pip wheel --wheel-dir=/opt/wheels -r /opt/duplicity-basic-requirements.txt && \
	# add backend dependencies here
	pip wheel --wheel-dir=/opt/wheels boto3

	# Copy the application source and requirements
COPY requirements* /opt/app/

# Install the application requirements into a separate wheel directory
RUN pip wheel --wheel-dir=/opt/wheels -r /opt/app/requirements-k8s.txt

# Stage 2: The Final Production Stage

FROM docker.io/python:3.12-alpine

# Copy the wheels from the build container
COPY --from=build /opt/wheels /tmp/wheels/

# Install the necessary runtime dependencies
RUN apk fix && \
    apk add --no-cache \
        ca-certificates \
        openssh \
        gpg \
        gpg-agent \
        librsync \
        gettext

    # Install Python packages from the pre-built wheels
RUN pip install --no-cache-dir --no-index --no-deps --find-links=/tmp/wheels/ /tmp/wheels/* && \
    # Clean up the wheels to reduce image size
    rm -rf /tmp/wheels && \
    # Add a dedicated, non-root user for security
    addgroup -S app && \
    adduser -S app -G app && \
    # Create necessary directories for the app and GPG keys
    mkdir -p \
        /home/app/.cache/duplicity \
        /home/app/.gnupg && \
    chown -R app:app /home/app 

# Copy the application source code
COPY src/*.py /opt/app/

# Set file permissions for the application files
RUN chown -R root:root /opt/app && \
    find /opt/app -type d -exec chmod 755 {} + && \
    find /opt/app -type f -exec chmod 644 {} +;

# Switch to the non-root user
USER app

# Define the entrypoint for the application
ENTRYPOINT ["python3", "-u", "/opt/app/backup.py"]