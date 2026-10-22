#!/bin/bash
for i in $(seq 120); do echo "tick $i"; sleep 1; done
echo ok > /app/answer
