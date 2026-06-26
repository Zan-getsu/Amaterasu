ARG BASE_IMAGE=nbots/amaterasu:v1
FROM ${BASE_IMAGE}

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Dhaka \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/amaterasuvenv \
    PATH="/amaterasuvenv/bin:${PATH}"

WORKDIR /usr/src/app

# Create the virtual environment (was missing)
RUN python3 -m venv /amaterasuvenv

# Install uv into the venv for fast package installation
RUN /amaterasuvenv/bin/pip install --no-cache-dir uv

# Install python dependencies using uv
COPY requirements.txt .
RUN /amaterasuvenv/bin/uv pip install --python /amaterasuvenv/bin/python --no-cache-dir -r requirements.txt

# Copy all the project files
COPY . .

# Setup permissions and convert Windows line endings to Unix just in case
RUN sed -i 's/\r$//' *.sh \
    && chmod +x start.sh

# Start the bot
CMD ["bash", "start.sh"]