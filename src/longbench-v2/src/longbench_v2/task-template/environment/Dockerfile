FROM python:3.12-slim

# The long context the question is about. Agents read it with their own tools.
WORKDIR /app
COPY context.txt /app/context.txt
RUN chmod 644 /app/context.txt
