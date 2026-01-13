# Unified Dockerfile for both dev and prod
# Usage:
#   Dev: docker build --target dev -t frontend:dev .
#   Prod: docker build --target prod -t frontend:prod .

# Development stage - runs React dev server
FROM node:18-alpine AS dev

WORKDIR /app

# React env vars - passed as build args (for when image is built)
ARG REACT_APP_VERSION=dev
ENV REACT_APP_VERSION=${REACT_APP_VERSION}

# Install dependencies
COPY package*.json ./
RUN npm install

# Copy source code and public assets for tests (needed in CI/CD where there's no volume mount)
COPY src/ ./src/
COPY public/ ./public/

EXPOSE 3000

# Start React dev server (code mounted as volume in docker-compose)
CMD ["npm", "start"]

# Production stage - builds and serves with nginx
FROM node:18-alpine AS builder

WORKDIR /app

# React env vars - passed as build args
ARG REACT_APP_BACKEND_URL
ARG REACT_APP_DOMAIN
ARG REACT_APP_FRONTEND_URL
ARG REACT_APP_ENVIRONMENT=production
ARG REACT_APP_VERSION=dev

# Set as ENV for build
ENV REACT_APP_BACKEND_URL=${REACT_APP_BACKEND_URL}
ENV REACT_APP_DOMAIN=${REACT_APP_DOMAIN}
ENV REACT_APP_FRONTEND_URL=${REACT_APP_FRONTEND_URL}
ENV REACT_APP_ENVIRONMENT=${REACT_APP_ENVIRONMENT}
ENV REACT_APP_VERSION=${REACT_APP_VERSION}

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# Production serve stage
FROM nginx:alpine AS prod

# Copy built app from builder
COPY --from=builder /app/build /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
