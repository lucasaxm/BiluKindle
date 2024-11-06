# Use an official Python runtime as a parent image
FROM python:3.10-slim

RUN apt-get update && apt-get install -y git && apt-get clean

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Clone the kcc repository and install its dependencies
RUN git clone https://github.com/lucasaxm/kcc /kcc
RUN pip install --no-cache-dir -r /kcc/requirements.txt

# Modify the kcc-c2e script to point to the correct kcc-c2e.py file
RUN chmod +x kcc-c2e
RUN cp kcc-c2e /usr/local/bin/

# Run bot.py when the container launches
CMD ["python", "run_bot.py"]
