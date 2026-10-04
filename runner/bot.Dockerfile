# Minimal Docker image for running user bots
# Based on python:3.11-slim but with a non-root user and minimal layers.

FROM python:3.11-slim

# Create a non-root user to run bots
RUN addgroup --system botgrp \
    && adduser --system --ingroup botgrp --home /home/botuser --shell /usr/sbin/nologin botuser

# Create /bot directory as mount point for the host; ensure permissions
RUN mkdir -p /bot && chown botuser:botgrp /bot && chmod 755 /bot

# Use a small entrypoint but allow override from docker run
WORKDIR /bot

# Switch to non-root user
USER botuser

# Default command (can be overridden by docker run)
ENTRYPOINT ["python3"]
CMD ["/bot/bot.py"]

