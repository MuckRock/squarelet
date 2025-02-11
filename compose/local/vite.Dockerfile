FROM node:22 AS base

# Set working directory
WORKDIR /app

# Install node modules
COPY package*.json ./
RUN npm install --include=dev

# Note: vite.config.js and src code will be mounted via volumes
# COPY . .
