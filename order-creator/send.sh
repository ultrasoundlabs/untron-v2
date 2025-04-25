#!/bin/bash

# Example curl command to create an order with Untron V2
curl -X POST "https://untron.finance/api/v2-staging/create-order" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": "TXYkMwWaHrPFfepurnsqYngrji6vxxHkX9",
    "amount": 1000000,
    "rate": 997000,
    "beneficiary": "0xf178905915f55dd34Ba1980942354dc64109118F"
  }' 