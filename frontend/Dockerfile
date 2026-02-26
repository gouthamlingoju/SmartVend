# Use an official Node.js runtime as a parent image
FROM node:20-alpine

# Set the working directory in the container
WORKDIR /app

# Copy package.json and package-lock.json (if available)
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application code
COPY . .

# Expose the port the app runs on
EXPOSE 5174

# Command to run the application in development mode
# Using --host 0.0.0.0 to allow access from outside the container
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
