# ChronoMark frontend: Vite build served by nginx.
#
# Build stage compiles the SPA; the API base is baked into the bundle at
# build time (Vite replaces import.meta.env.VITE_API_URL). The default
# http://localhost:8000 matches where compose publishes the backend.

FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# Serve stage: nginx with a SPA fallback so deep links like /upload work.
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
