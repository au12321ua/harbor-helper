#!/bin/bash
# Records whether the verification phase could reach the internet, then scores.
net-probe > /logs/verifier/probe.txt
if [ -f /app/answer ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
