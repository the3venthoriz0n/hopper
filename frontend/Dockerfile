FROM node:18-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

# Copy all files (public and src will be overridden by volume mounts in dev)
COPY . .

# React env vars must be available at build time
# These are passed as build args and then set as env vars
ARG REACT_APP_BACKEND_URL
ARG REACT_APP_DOMAIN
ARG REACT_APP_FRONTEND_URL

ENV REACT_APP_BACKEND_URL=${REACT_APP_BACKEND_URL}
ENV REACT_APP_DOMAIN=${REACT_APP_DOMAIN}
ENV REACT_APP_FRONTEND_URL=${REACT_APP_FRONTEND_URL}

EXPOSE 3000

CMD ["npm", "start"]

