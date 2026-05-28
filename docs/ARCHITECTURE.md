# ESPAI Architecture

ESPAI has three execution zones:

1. Hub
2. Workers
3. Nodes

The hub manages registry, dashboard, cards, recipes, workers, policies, firmware, OTA, design, notifications, storage, and logs.

Workers process images, video, telemetry, protocol captures, logs, and sensor data.

Nodes are ESP32-class devices that interact with hardware, expose minimal APIs, check in, operate offline, receive OTA, and run safety logic locally.

Realtime projects may use direct browser-to-node connections for RC control and camera streams.
