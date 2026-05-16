# syntax=docker/dockerfile:1.7

# Stage 1: build the SvelteKit static bundle.
FROM node:22-alpine AS builder
WORKDIR /app

# Install deps first so dependency layers cache when only source files change.
COPY package.json package-lock.json ./
RUN npm ci

# Then copy the rest of the source and build. The build/ output is what we
# hand off to Nginx; .svelte-kit/ is intermediate and stays in this stage.
COPY . .
RUN npm run build

# Stage 2: serve the static bundle behind Nginx.
FROM nginx:1.27-alpine AS runtime

# Replace the stock default.conf with our SPA + reverse-proxy config.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static assets live where Nginx expects them.
COPY --from=builder /app/build /usr/share/nginx/html

EXPOSE 80
