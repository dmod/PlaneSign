---
description: "Use when changing the Docker image, the installer or the nginx config: Dockerfile, docker_install_and_update.sh, docker_nginx_planesign.conf, .python-version. Covers the Python/venv linkage and Docker's repository format."
applyTo: "Dockerfile, docker_install_and_update.sh, docker_nginx_planesign.conf, .python-version"
---
# Docker Image And Installer

- The image's `.venv` links to Ubuntu's system Python, and the runtime stage copies only `.venv` and installs the matching `python3`/`libpython` packages. The builder sets `UV_PYTHON_DOWNLOADS=never`, so a `.python-version` that the base image cannot satisfy fails the build. Without it, the venv would link to a uv-managed interpreter that the runtime stage lacks.
- Changing the Ubuntu base image means updating `.python-version`, `CFLAGS` and the `libpython` package together.
- The installer uses Docker's current Debian repository format (`docker.sources` and `docker.asc`). It removes its legacy `docker.list` before APT recovery when `docker.sources` already exists, and before configuring the modern repository.
- The nginx config serves `web/` on 80/443 and proxies `/api/` to the Flask API on 5055, rewriting the `/api/` prefix away.
