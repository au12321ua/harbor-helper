#!/bin/bash
# Reward 1 only if the reference solution left its answer; otherwise a real 0.
echo "verifying /app/answer"
if [ -f /app/answer ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
