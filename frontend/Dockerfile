FROM node:18-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

# Copy all files (public and src will be overridden by volume mounts in dev)
COPY . .

EXPOSE 3000

CMD ["npm", "start"]

