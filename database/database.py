# import json
# import torch
# from kafka import KafkaConsumer, KafkaProducer
# import time

# # --- Configuration ---
# KAFKA_BROKER = 'localhost:9092'
# INPUT_TOPIC = 'final_analysis_alerts'
# OUTPUT_TOPIC = 'suspicious_features_gallery' # Topic to broadcast the gallery

# # --- Kafka Clients ---
# consumer = KafkaConsumer(INPUT_TOPIC, bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
# producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

# # --- In-memory "DataBase" for suspicious features ---
# # This is our gallery of known suspicious individuals' fingerprints
# suspicious_gallery = []

# print("Database Service is running...")

# while True:
#     # 1. Listen for new suspicious alerts and add their features to our gallery
#     messages = consumer.poll(timeout_ms=1000, max_records=100)
#     for topic_partition, records in messages.items():
#         for record in records:
#             alert = record.value
#             # CHANGED: Check if the suspicion score is > 0.5 and a feature exists
#             if 'analysis' in alert and alert['analysis'].get('suspicion_score', 0) > 0.0 and 'feature' in alert and alert['feature']:
#                 new_feature = torch.tensor(alert['feature'])
#                 # Add the feature to the gallery if it's not already there
#                 is_new = True
#                 for existing_feature in suspicious_gallery:
#                     # A simple check to avoid adding the exact same feature multiple times
#                     if torch.equal(new_feature, existing_feature):
#                         is_new = False
#                         break
#                 if is_new:
#                     suspicious_gallery.append(new_feature)
#                     print(f"New suspicious feature added to database (Score > 0.5). Total size: {len(suspicious_gallery)}")

#     # 2. Periodically publish the entire gallery for other services to use
#     if suspicious_gallery:
#         # Convert list of tensors to a list of lists for JSON
#         gallery_to_send = [f.tolist() for f in suspicious_gallery]
#         output_data = {"gallery": gallery_to_send}
#         producer.send(OUTPUT_TOPIC, value=output_data)
#         print(f"Broadcasted suspicious feature gallery with {len(suspicious_gallery)} items.")
    
#     # Broadcast every 5 seconds
#     time.sleep(5)

import json
import torch
from kafka import KafkaConsumer, KafkaProducer
import time

# --- Configuration ---
KAFKA_BROKER = 'kafka:29092'
INPUT_TOPIC = 'final_analysis_alerts'
OUTPUT_TOPIC = 'suspicious_features_gallery'

# --- Kafka Clients ---
consumer = KafkaConsumer(INPUT_TOPIC, bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

# --- In-memory "DataBase" ---
suspicious_gallery = []

print("Database Service is running...")

while True:
    messages = consumer.poll(timeout_ms=1000, max_records=100)
    if not messages:
        # If no messages, just broadcast the gallery and continue
        if suspicious_gallery:
            gallery_to_send = [f.tolist() for f in suspicious_gallery]
            producer.send(OUTPUT_TOPIC, value={"gallery": gallery_to_send})
        time.sleep(5)
        continue

    for topic_partition, records in messages.items():
        for record in records:
            alert = record.value
            print("\nDEBUG: Received an alert from the reasoning service.") # DEBUG PRINT 1

            # --- The Gatekeeper Check ---
            analysis = alert.get('analysis', {})
            score = analysis.get('suspicion_score', 0)
            has_feature = 'feature' in alert and alert['feature']

            if score > 0.5 and has_feature:
                print("DEBUG: Alert PASSED the filter. Adding to gallery.") # DEBUG PRINT 2
                new_feature = torch.tensor(alert['feature'])
                is_new = all(not torch.equal(new_feature, f) for f in suspicious_gallery)
                if is_new:
                    suspicious_gallery.append(new_feature)
                    print(f"SUCCESS: New suspicious feature added. Total size: {len(suspicious_gallery)}")
            else:
                # This will tell us exactly why a message was ignored
                print("DEBUG: Alert IGNORED. Reason:") # DEBUG PRINT 3
                if score <= 0.5:
                    print(f"  - Suspicion score ({score:.2f}) was not > 0.5")
                if not has_feature:
                    print("  - Alert was missing the 'feature' vector.")

    # Periodically publish the entire gallery for other services to use
    if suspicious_gallery:
        gallery_to_send = [f.tolist() for f in suspicious_gallery]
        output_data = {"gallery": gallery_to_send}
        producer.send(OUTPUT_TOPIC, value=output_data)
        print(f"Broadcasted suspicious feature gallery with {len(suspicious_gallery)} items.")
    
    time.sleep(5)