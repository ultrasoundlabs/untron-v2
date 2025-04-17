import asyncio
import os
import json
import base58
from web3 import Web3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from tronpy import AsyncTron
from tronpy.providers import AsyncHTTPProvider
import uvicorn
from pydantic import BaseModel
from typing import Dict

# Load environment variables
load_dotenv()

# Configuration
ETH_NODE = os.getenv("RPC_URL")
CONTRACT_ADDRESS = os.getenv("UNTRON_CONTRACT_ADDRESS")
PRIVATE_KEY = os.getenv("ORDER_CREATOR_PRIVATE_KEY")

# USDT TRC20 token contract address on Tron
TRON_USDT_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# Load contract ABI from a file or define it inline
CONTRACT_ABI = json.load(open("out/UntronV2.json"))["abi"]

# Setup clients
w3 = Web3(Web3.HTTPProvider(ETH_NODE))
contract = w3.eth.contract(
    address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=CONTRACT_ABI
)

# Initialize Ethereum account
account = w3.eth.account.from_key(PRIVATE_KEY)

# Initialize Tron client
tron_provider = AsyncHTTPProvider(api_key=os.getenv("TRONGRID_API_KEY"))
tron = AsyncTron(tron_provider)

# USDT contract will be initialized later
usdt_contract = None

async def initialize_usdt_contract():
    global usdt_contract
    usdt_contract = await tron.get_contract(TRON_USDT_ADDRESS)

# Set up FastAPI app
app = FastAPI(title="Untron V2 Order API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    await initialize_usdt_contract()

# Request model
class OrderRequest(BaseModel):
    receiver: str  # Tron address
    amount: int  # Amount in USDT (Sun units)
    rate: int  # Rate for conversion
    beneficiary: str  # Ethereum address

# Active orders storage - mapping receiver address to initial balance
active_orders: Dict[str, Dict] = {}

async def get_tron_usdt_balance(address: str) -> int:
    """Get USDT balance for a Tron address"""
    balance = await usdt_contract.functions.balanceOf(address)
    return balance

async def monitor_and_set_claim(receiver: str):
    """
    Monitor USDT balance changes for 10 minutes and then set claim
    based on the difference from initial balance
    """
    try:
        # Get stored data
        order_data = active_orders[receiver]
        initial_balance = order_data["initial_balance"]
        order_request = order_data["order"]
        
        # Wait for 10 minutes
        await asyncio.sleep(600)  # 10 minutes = 600 seconds
        
        # Get final balance
        final_balance = await get_tron_usdt_balance(receiver)
        
        # Calculate balance difference
        balance_diff = initial_balance - final_balance
        
        # Only set claim if balance difference doesn't match the expected order amount
        if balance_diff != order_request.amount:
            # Prepare transaction to set claim
            receiver_bytes = base58.b58decode_check(receiver)[1:]
            nonce = w3.eth.get_transaction_count(account.address)
                
            tx = contract.functions.setClaim(
                receiver_bytes,
                balance_diff
            ).build_transaction({
                'from': account.address,
                'nonce': nonce,
                'gas': 200000,
                'gasPrice': w3.eth.gas_price
            })
                
            # Sign and send transaction
            signed_tx = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                
            # Wait for transaction receipt
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                
            print(f"Claim set for receiver {receiver} with amount {balance_diff}")
            print(f"Transaction hash: {receipt.transactionHash.hex()}")
        else:
            print(f"No claim needed for receiver {receiver} as balance difference ({balance_diff}) matches order amount")
        
        # Remove from active orders
        if receiver in active_orders:
            del active_orders[receiver]
            
    except Exception as e:
        print(f"Error in monitor_and_set_claim for {receiver}: {str(e)}")
        if receiver in active_orders:
            del active_orders[receiver]

@app.post("/create-order", status_code=201)
async def create_order(order: OrderRequest):
    try:
        # Validate Tron address format
        try:
            decoded = base58.b58decode_check(order.receiver)
            if len(decoded) != 21 or decoded[0] != 0x41:
                raise HTTPException(status_code=400, detail="Invalid Tron address format")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Tron address format: {e}")
        # Get current USDT balance
        initial_balance = await get_tron_usdt_balance(order.receiver)
        
        # Store order data and initial balance for later comparison
        active_orders[order.receiver] = {
            "initial_balance": initial_balance,
            "order": order
        }
        
        # Convert Tron address to bytes20 format expected by Ethereum contract
        receiver_bytes = decoded[1:]
        
        # Prepare transaction
        nonce = w3.eth.get_transaction_count(account.address)
        
        tx = contract.functions.createOrder(
            receiver_bytes,
            order.amount,
            order.rate,
            Web3.to_checksum_address(order.beneficiary)
        ).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gas': 200000,
            'gasPrice': w3.eth.gas_price
        })
        
        # Sign and send transaction
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        # Wait for transaction receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        # Start background task to monitor balance and set claim after 10 minutes
        asyncio.create_task(monitor_and_set_claim(order.receiver))
        
        return {
            "status": "success",
            "message": "Order created successfully",
            "transaction_hash": receipt.transactionHash.hex(),
            "initial_balance": initial_balance,
            "monitoring_period": 600
        }
        
    except Exception as e:
        # Clean up if there was an error
        if order.receiver in active_orders:
            del active_orders[order.receiver]
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("order-creator.main:app", host="0.0.0.0", port=8456, reload=True)