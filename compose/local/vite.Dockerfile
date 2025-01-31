FROM --platform=linux/arm64 node:22 as base

# Set working directory
WORKDIR /app

# Install node modules
COPY package*.json ./
RUN npm install

# Note: vite.config.js and src code will be mounted via volumes
