FROM node:22-slim AS frontend-deps

WORKDIR /home/frontend/

COPY package.json ./package.json
COPY package-lock.json ./package-lock.json

RUN npm ci

COPY .dockerignore ./.dockerignore
# COPY ./src/frontend/.prettierrc.js ./.prettierrc.js
#COPY ./src/frontend/packages/eslint-config-messages ./packages/eslint-config-messages
COPY . ./apps/messages

### ---- Front-end builder image ----
FROM frontend-deps AS st-messages-dev

WORKDIR /home/frontend/apps/messages

EXPOSE 3000

CMD [ "npm", "run", "dev"]

# Tilt will rebuild messages target so, we dissociate messages and messages-builder 
# to avoid rebuilding the app at every changes.
FROM frontend-deps AS messages-builder

WORKDIR /home/frontend/apps/messages

ARG S3_DOMAIN_REPLACE
ENV NEXT_PUBLIC_S3_DOMAIN_REPLACE=${S3_DOMAIN_REPLACE}

RUN npm run build

# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files
COPY package.json ./package.json
COPY package-lock.json ./package-lock.json

# Install all dependencies (needed for build)
RUN npm ci --no-audit --no-fund

# Copy source code
COPY . .

# Build application
ENV NODE_ENV=production

RUN npm run build && npm prune --production

# Production stage
FROM node:22-alpine AS production

WORKDIR /app

# No need to install deps - copying from builder

# Copy standalone application
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Create non-root user
RUN addgroup -g 1001 -S nodejs
RUN adduser -S nextjs -u 1001
USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]