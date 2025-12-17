# Multi-stage build for production
# Stage 1: Build React app
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

# Stage 2: Serve with nginx
FROM nginx:alpine

# Copy built app from builder
COPY --from=builder /app/build /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
