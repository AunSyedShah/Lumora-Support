# Frontend image: Node 22 running the Vite dev server, with Bun installing the packages (the repo's lockfile is bun.lock).
# The source code is NOT copied in: docker-compose.yml mounts ./frontend at /app. node_modules lives in a Docker volume,
# so the Windows node_modules on your PC are never used and installs stay fast.
FROM node:22-slim

RUN npm install -g bun@1 && npm cache clean --force

COPY docker-entrypoint.sh /usr/local/bin/entrypoint.sh
# Windows checkouts can turn line endings into CRLF, which breaks shell scripts: strip them.
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /app
EXPOSE 5173
ENTRYPOINT ["entrypoint.sh"]
CMD ["node_modules/.bin/vite", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
