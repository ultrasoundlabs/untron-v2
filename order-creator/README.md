# Untron V2 Order API

This example demonstrates how to use cURL to create an order with the Untron V2 Order API.

## Create Order Endpoint

```bash
curl -X POST "http://localhost:8000/create-order" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": "TXhZ1RDMxdW5TQhYTbhgjqS74NeQ5Gn9WP",
    "amount": 1000000,
    "rate": 98,
    "beneficiary": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
  }'
```

### Parameters:

- `receiver`: Tron address where USDT will be sent (must be a valid Tron address)
- `amount`: Amount in USDT (in Sun units - smallest unit of USDT on Tron)
- `rate`: Rate for conversion
- `beneficiary`: Ethereum address where funds will be sent after claim

### Expected Response:

```json
{
  "status": "success",
  "message": "Order created successfully",
  "transaction_hash": "0x...",
  "initial_balance": 0,
  "monitoring_period": 600
}
```

Note that the API will monitor the balance of the receiver address for 10 minutes (600 seconds) after order creation. 