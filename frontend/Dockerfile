# Build stage
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# Build args for Vite env vars (set in Render dashboard)
ARG VITE_BACKEND_URL
ARG VITE_RAZORPAY_KEY_ID
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_PRICE_PER_UNIT=1

RUN npm run build

# Production stage — serve static files
FROM node:20-alpine

WORKDIR /app

RUN npm install -g serve

COPY --from=build /app/dist ./dist

EXPOSE 10000

CMD ["serve", "-s", "dist", "-l", "10000"]
