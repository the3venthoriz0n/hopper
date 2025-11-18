FROM node:18-alpine

WORKDIR /app

# React env vars - passed as build args (for build-time) and runtime env vars
ARG REACT_APP_BACKEND_URL
ARG REACT_APP_DOMAIN
ARG REACT_APP_FRONTEND_URL

# Set as ENV so they're available at runtime too
ENV REACT_APP_BACKEND_URL=${REACT_APP_BACKEND_URL}
ENV REACT_APP_DOMAIN=${REACT_APP_DOMAIN}
ENV REACT_APP_FRONTEND_URL=${REACT_APP_FRONTEND_URL}

COPY package*.json ./
RUN npm install

# Copy source files (node_modules will be in volume for dev)
COPY . .

EXPOSE 3000

# Create .env file from runtime env vars and start app
# Create React App reads .env files when npm start runs
# Hot reload enabled via volume mounts and polling (CHOKIDAR_USEPOLLING)
CMD sh -c 'echo "REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL" > .env && \
           echo "REACT_APP_DOMAIN=$REACT_APP_DOMAIN" >> .env && \
           echo "REACT_APP_FRONTEND_URL=$REACT_APP_FRONTEND_URL" >> .env && \
           npm start'

