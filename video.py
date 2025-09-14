import cv2
import time
import json
import logging
from kafka import KafkaProducer
from kafka.errors import KafkaError

# --- Configuration ---
KAFKA_BROKER = 'localhost:9092'
# KAFKA_BROKER = '10.139.40.73:9092'
OUTPUT_TOPIC = 'raw_video_frames'
CAMERA_ID = "Camera_01_Lobby"
VIDEO_SOURCE = 0 # Use 0 for webcam, or a path to a video file/RTSP stream
FPS = 2 # Desired frames per second to process

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_kafka_producer():
    """Creates and returns a Kafka producer."""
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            retries=5 # Retry sending on failure
        )
        logging.info("Kafka producer created successfully.")
        return producer
    except KafkaError as e:
        logging.error(f"Error creating Kafka producer: {e}")
        return None

def main():
    producer = create_kafka_producer()
    if not producer:
        return

    cap = None
    while True:
        try:
            # If camera is not opened, try to open it
            if cap is None or not cap.isOpened():
                logging.info(f"Attempting to open video source: {VIDEO_SOURCE}")
                cap = cv2.VideoCapture(VIDEO_SOURCE)
                if not cap.isOpened():
                    logging.error("Could not open video source. Retrying in 5 seconds...")
                    time.sleep(5)
                    continue
                logging.info("Video source opened successfully.")

            ret, frame = cap.read()
            if not ret:
                logging.warning("Failed to grab frame. Reconnecting...")
                cap.release()
                cap = None # Force re-opening in the next loop
                time.sleep(5)
                continue

            # Encode frame to JPEG and then to a hex string
            _, buffer = cv2.imencode('.jpg', frame)
            frame_hex = buffer.tobytes().hex()

            # Prepare data payload
            data = {
                "camera_id": CAMERA_ID,
                "timestamp": time.time(),
                "frame_hex": frame_hex
            }

            # Send data to Kafka
            producer.send(OUTPUT_TOPIC, value=data)
            logging.info(f"Sent frame with timestamp {data['timestamp']}")
            
            # Flush messages to ensure they are sent
            producer.flush()
            
            # Control the frame rate
            time.sleep(1 / FPS)

        except KeyboardInterrupt:
            logging.info("Interruption detected. Shutting down.")
            break
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            time.sleep(5)
        
    if cap and cap.isOpened():
        cap.release()
    if producer:
        producer.close()
    logging.info("Shutdown complete.")

if __name__ == "__main__":
    main()